"""组件清洗数据持久化层：SQLite 落库，清洗任务与巡视联动待办都存这里。

其余业务模块仍走内存仓库，只有组件清洗改成真实落库。
首次启动若库表为空，会把内存里的旧台账按计划日期顺序回填，
并为其中已完成的任务补建巡视待办；之后一律以库里的数据为准。
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from app.seed import SEED_ROWS

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ops.db"

# 清洗状态沿「计划 → 执行中 → 已完成」依次推进，只保留这三个口径。
STATUS_PLANNED = "计划"
STATUS_RUNNING = "执行中"
STATUS_DONE = "已完成"
STATUS_ORDER = [STATUS_PLANNED, STATUS_RUNNING, STATUS_DONE]

# 老台账里用过的状态名，回填时统一折算到新口径；新口径自身也列入，保证幂等。
LEGACY_STATUS_MAP = {
    "待排期": STATUS_PLANNED,
    "已排期": STATUS_PLANNED,
    "计划": STATUS_PLANNED,
    "作业中": STATUS_RUNNING,
    "执行中": STATUS_RUNNING,
    "已完成": STATUS_DONE,
}

ENTRY_FIELDS = ["任务编号", "清洗区域", "清洗方式", "计划日期", "作业人员", "用水吨数", "清洗后PR值"]

_DDL_TASKS = """
CREATE TABLE IF NOT EXISTS cleaning_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_no TEXT NOT NULL UNIQUE,
    area TEXT NOT NULL,
    method TEXT NOT NULL,
    plan_date TEXT NOT NULL,
    workers TEXT,
    water_tons REAL NOT NULL DEFAULT 0,
    pr_after REAL,
    status TEXT NOT NULL DEFAULT '计划',
    created_at TEXT NOT NULL
)
"""

_DDL_FOLLOWUPS = """
CREATE TABLE IF NOT EXISTS cleaning_patrol_followups (
    task_id INTEGER PRIMARY KEY,
    task_no TEXT NOT NULL,
    area TEXT NOT NULL,
    plan_date TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _to_float(value: Any) -> float:
    """老台账里用水吨数/PR 值可能是占位文字，解析不出来就按空处理，不进汇总。"""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": row["status"],
        "pending": row["status"] != STATUS_DONE,
        "abnormal": False,
        "任务编号": row["task_no"],
        "清洗区域": row["area"],
        "清洗方式": row["method"],
        "计划日期": row["plan_date"],
        "作业人员": row["workers"] or "",
        # 未登记用水时统一给 0，保证列表与按区域汇总永远对得上。
        "用水吨数": round(row["water_tons"], 2),
        "清洗后PR值": round(row["pr_after"], 2) if row["pr_after"] is not None else None,
        "清洗状态": row["status"],
    }


def _bootstrap(conn: sqlite3.Connection) -> None:
    """首启回填：旧任务沿用原有区域归属，按计划日期顺序入库。"""
    count = conn.execute("SELECT COUNT(*) FROM cleaning_tasks").fetchone()[0]
    if count:
        return
    legacy = [dict(row) for row in SEED_ROWS.get("cleaning", [])]

    def _plan_key(row: dict[str, Any]) -> str:
        return str(row.get("计划日期") or "")

    for row in sorted(legacy, key=_plan_key):
        raw_status = str(row.get("status") or row.get("清洗状态") or STATUS_PLANNED)
        status = LEGACY_STATUS_MAP.get(raw_status, raw_status if raw_status in STATUS_ORDER else STATUS_PLANNED)
        plan_date = str(row.get("计划日期") or date.today().isoformat())
        pr_value = row.get("清洗后PR值")
        conn.execute(
            "INSERT INTO cleaning_tasks "
            "(id, task_no, area, method, plan_date, workers, water_tons, pr_after, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(row.get("id", 0)),
                str(row.get("任务编号") or ""),
                str(row.get("清洗区域") or ""),
                str(row.get("清洗方式") or ""),
                plan_date,
                str(row.get("作业人员") or ""),
                _to_float(row.get("用水吨数")),
                _to_float(pr_value) if pr_value not in (None, "") else None,
                status,
                plan_date,
            ),
        )
        if status == STATUS_DONE:
            conn.execute(
                "INSERT OR IGNORE INTO cleaning_patrol_followups "
                "(task_id, task_no, area, plan_date, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    int(row.get("id", 0)),
                    str(row.get("任务编号") or ""),
                    str(row.get("清洗区域") or ""),
                    plan_date,
                    plan_date,
                ),
            )
    conn.commit()


def init_db() -> None:
    with _connect() as conn:
        conn.execute(_DDL_TASKS)
        conn.execute(_DDL_FOLLOWUPS)
        _bootstrap(conn)


def _build_where(
    *,
    area: str | None = None,
    method: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    keyword: str | None = None,
    status: str | None = None,
) -> tuple[str, list[Any]]:
    """列表、汇总、导出共用同一份筛选口径。"""
    clauses: list[str] = []
    params: list[Any] = []
    if area:
        clauses.append("area = ?")
        params.append(area)
    if method:
        clauses.append("method = ?")
        params.append(method)
    if date_from:
        clauses.append("plan_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("plan_date <= ?")
        params.append(date_to)
    if keyword:
        clauses.append("task_no LIKE ?")
        params.append(f"%{keyword}%")
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def list_tasks(
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
    where, params = _build_where(
        area=area, method=method, date_from=date_from, date_to=date_to,
        keyword=keyword, status=status,
    )
    with _connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM cleaning_tasks{where}", params).fetchone()[0]
        start = max(page - 1, 0) * size
        rows = conn.execute(
            f"SELECT * FROM cleaning_tasks{where} ORDER BY plan_date DESC, id DESC LIMIT ? OFFSET ?",
            [*params, size, start],
        ).fetchall()
    return [_task_from_row(row) for row in rows], int(total)


def all_tasks(
    *,
    area: str | None = None,
    method: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    keyword: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """导出与汇总用：不分页，筛选口径与列表完全一致。"""
    where, params = _build_where(
        area=area, method=method, date_from=date_from, date_to=date_to,
        keyword=keyword, status=status,
    )
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM cleaning_tasks{where} ORDER BY plan_date DESC, id DESC",
            params,
        ).fetchall()
    return [_task_from_row(row) for row in rows]


def get_task(entry_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM cleaning_tasks WHERE id = ?", (entry_id,)).fetchone()
    return _task_from_row(row) if row else None


def get_task_by_no(task_no: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM cleaning_tasks WHERE task_no = ?", (task_no,)).fetchone()
    return _task_from_row(row) if row else None


def create_task(values: dict[str, Any]) -> dict[str, Any]:
    today = date.today().isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO cleaning_tasks "
            "(task_no, area, method, plan_date, workers, water_tons, pr_after, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(values.get("任务编号", "")).strip(),
                str(values.get("清洗区域", "")).strip(),
                str(values.get("清洗方式", "")).strip(),
                str(values.get("计划日期") or today),
                str(values.get("作业人员") or "").strip(),
                _to_float(values.get("用水吨数")),
                _to_float(values["清洗后PR值"]) if str(values.get("清洗后PR值") or "").strip() else None,
                STATUS_PLANNED,
                today,
            ),
        )
        conn.commit()
        task_id = cursor.lastrowid
        row = conn.execute("SELECT * FROM cleaning_tasks WHERE id = ?", (task_id,)).fetchone()
    return _task_from_row(row)


def set_task_status(entry_id: int, status: str) -> tuple[dict[str, Any] | None, str]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM cleaning_tasks WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            return None, f"清洗任务 {entry_id} 不存在或已归档"
        current = row["status"]
        if status == current:
            return _task_from_row(row), f"清洗任务已是「{current}」状态，请勿重复提交"

        task_no, area, plan_date = row["task_no"], row["area"], row["plan_date"]
        if status == STATUS_RUNNING and current == STATUS_PLANNED:
            message = "清洗任务已开始执行"
        elif status == STATUS_DONE and current == STATUS_RUNNING:
            message = "清洗任务已完成验收"
        elif status == STATUS_RUNNING and current == STATUS_DONE:
            # 已完成的任务再点执行：退回执行中，同时撤掉它产生的巡视待办。
            message = "已完成的清洗任务已退回执行中"
        else:
            return _task_from_row(row), (
                f"清洗任务当前为「{current}」，只能沿「{STATUS_PLANNED} → {STATUS_RUNNING} → {STATUS_DONE}」推进，不能改为「{status}」"
            )

        conn.execute("UPDATE cleaning_tasks SET status = ? WHERE id = ?", (status, entry_id))
        if status == STATUS_DONE:
            conn.execute(
                "INSERT OR IGNORE INTO cleaning_patrol_followups "
                "(task_id, task_no, area, plan_date, created_at) VALUES (?, ?, ?, ?, ?)",
                (entry_id, task_no, area, plan_date, date.today().isoformat()),
            )
        elif status == STATUS_RUNNING:
            conn.execute("DELETE FROM cleaning_patrol_followups WHERE task_id = ?", (entry_id,))
        conn.commit()
        row = conn.execute("SELECT * FROM cleaning_tasks WHERE id = ?", (entry_id,)).fetchone()
    return _task_from_row(row), message


def list_options() -> dict[str, list[str]]:
    with _connect() as conn:
        areas = [r[0] for r in conn.execute(
            "SELECT DISTINCT area FROM cleaning_tasks WHERE area <> '' ORDER BY area")]
        methods = [r[0] for r in conn.execute(
            "SELECT DISTINCT method FROM cleaning_tasks WHERE method <> '' ORDER BY method")]
    return {"areas": areas, "methods": methods}


def count_tasks() -> int:
    with _connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM cleaning_tasks").fetchone()[0])


def count_pending_tasks() -> int:
    with _connect() as conn:
        return int(conn.execute(
            f"SELECT COUNT(*) FROM cleaning_tasks WHERE status != ?", (STATUS_DONE,)).fetchone()[0])


def list_followups() -> list[dict[str, Any]]:
    """清洗完成后计入巡视的待办，按计划日期倒序。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM cleaning_patrol_followups ORDER BY plan_date DESC, task_id DESC"
        ).fetchall()
    return [
        {
            # 负数 id 与巡视自身记录错开，前端据此隐藏动作按钮。
            "id": -int(row["task_id"]),
            "status": "待巡视",
            "pending": True,
            "abnormal": False,
            "记录编号": f"QXHS-{int(row['task_id']):04d}",
            "巡视区域": row["area"],
            "巡视日期": row["plan_date"],
            "巡视人员": "待安排（清洗联动）",
            "发现缺陷数": "—",
            "红外测温结果": "—",
            "接线端子温度": "—",
            "巡视状态": "待巡视",
            "来源": "清洗联动",
        }
        for row in rows
    ]


def count_followups() -> int:
    with _connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM cleaning_patrol_followups").fetchone()[0])


# 导入即用：建表并完成旧台账回填。
init_db()
