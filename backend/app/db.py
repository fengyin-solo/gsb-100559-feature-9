"""SQLite 持久层：组件清洗与巡视检查落库，其他模块仍走内存示例数据。

设计要点：
- 只依赖标准库 sqlite3，克隆即用；数据库文件位置可用环境变量 OPS_DB_PATH 覆盖。
- 清洗状态统一为「计划 / 执行中 / 已完成」三态，历史四态数据在初始化时按规则归并。
- 巡视记录用 source_task 关联来源清洗任务：清洗验收后生成巡视待办，退回时撤销。
- 用水汇总与清洗列表共用 _query_cleaning 这一份筛选口径，保证两边数字对得上。
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date
from typing import Any, Iterator

DB_PATH = os.environ.get(
    "OPS_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ops.db"),
)

# 清洗状态沿「计划 → 执行中 → 已完成」依次推进。
CLEANING_STATUS_PLAN = "计划"
CLEANING_STATUS_DOING = "执行中"
CLEANING_STATUS_DONE = "已完成"
CLEANING_STATUSES = [CLEANING_STATUS_PLAN, CLEANING_STATUS_DOING, CLEANING_STATUS_DONE]

# 历史四态到三态的归并口径：待排期、已排期都算计划阶段。
LEGACY_STATUS_MAP = {
    "待排期": CLEANING_STATUS_PLAN,
    "已排期": CLEANING_STATUS_PLAN,
    "作业中": CLEANING_STATUS_DOING,
    "已完成": CLEANING_STATUS_DONE,
}

CLEANING_COLUMNS = [
    "任务编号",
    "清洗区域",
    "清洗方式",
    "计划日期",
    "作业人员",
    "用水吨数",
    "清洗后PR值",
]
PATROL_COLUMNS = [
    "记录编号",
    "巡视区域",
    "巡视日期",
    "巡视人员",
    "发现缺陷数",
    "红外测温结果",
    "接线端子温度",
]


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """打开一个短连接：行按字典取，提交/回滚由上下文统一兜底。"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 初始化与种子数据
# ---------------------------------------------------------------------------

def init_db() -> None:
    """建表并在空库时写入种子数据；重复启动不会产生第二条。"""
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cleaning (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_no TEXT NOT NULL UNIQUE,
                area TEXT NOT NULL,
                method TEXT NOT NULL,
                plan_date TEXT NOT NULL,
                workers TEXT DEFAULT '',
                water_tons REAL DEFAULT 0,
                pr_after REAL,
                status TEXT NOT NULL DEFAULT '计划',
                abnormal INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS patrol (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_no TEXT NOT NULL UNIQUE,
                area TEXT NOT NULL,
                patrol_date TEXT NOT NULL DEFAULT '',
                inspector TEXT DEFAULT '',
                defect_count INTEGER DEFAULT 0,
                infrared_result TEXT DEFAULT '',
                terminal_temp TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT '待巡视',
                abnormal INTEGER NOT NULL DEFAULT 0,
                source_task INTEGER,
                FOREIGN KEY (source_task) REFERENCES cleaning (id) ON DELETE SET NULL
            );
            """
        )
        _seed_if_empty(conn)


def _seed_if_empty(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) FROM cleaning").fetchone()[0] == 0:
        # 示例台账：覆盖不同区域、清洗方式、状态与计划日期，用水吨数为可汇总的数值。
        seed_cleaning = [
            ("CLEA-0001", "一号光伏区A排", "干式除尘", "2026-09-01", "张强、李伟", 12.5, 84.2, CLEANING_STATUS_DONE),
            ("CLEA-0002", "一号光伏区B排", "高压水洗", "2026-09-03", "王敏", 28.0, 85.6, CLEANING_STATUS_DONE),
            ("CLEA-0003", "二号光伏区A排", "干式除尘", "2026-09-05", "赵磊", 10.0, 83.9, CLEANING_STATUS_DOING),
            ("CLEA-0004", "二号光伏区B排", "机器人清洗", "2026-09-08", "清洗机器人02", 6.5, None, CLEANING_STATUS_PLAN),
            ("CLEA-0005", "三号光伏区A排", "高压水洗", "2026-09-10", "陈芳、刘涛", 31.5, None, CLEANING_STATUS_PLAN),
            ("CLEA-0006", "三号光伏区B排", "干式除尘", "2026-09-12", "孙鹏", 11.0, None, CLEANING_STATUS_PLAN),
            ("CLEA-0007", "一号光伏区A排", "机器人清洗", "2026-09-15", "清洗机器人01", 7.0, 86.1, CLEANING_STATUS_DONE),
            ("CLEA-0008", "一号光伏区B排", "高压水洗", "2026-09-18", "张强、周倩", 26.5, None, CLEANING_STATUS_DOING),
            ("CLEA-0009", "二号光伏区A排", "干式除尘", "2026-09-21", "赵磊", 9.5, None, CLEANING_STATUS_PLAN),
            ("CLEA-0010", "三号光伏区A排", "机器人清洗", "2026-09-25", "清洗机器人03", 6.0, None, CLEANING_STATUS_PLAN),
            ("CLEA-0011", "二号光伏区B排", "高压水洗", "2026-09-28", "陈芳", 30.0, None, CLEANING_STATUS_PLAN),
            ("CLEA-0012", "一号光伏区A排", "干式除尘", "2026-10-02", "李伟", 13.0, None, CLEANING_STATUS_PLAN),
        ]
        conn.executemany(
            """
            INSERT INTO cleaning
                (task_no, area, method, plan_date, workers, water_tons, pr_after, status, abnormal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            seed_cleaning,
        )

    if conn.execute("SELECT COUNT(*) FROM patrol").fetchone()[0] == 0:
        seed_patrol = [
            ("PATR-0001", "一号升压站", "2026-09-02", "夜班巡视组", 0, "无异常", "38.5℃", "已记录", 0, None),
            ("PATR-0002", "二号光伏区A排", "2026-09-06", "赵磊", 1, "组件热斑1处", "52.1℃", "巡视中", 1, None),
            ("PATR-0003", "储能电池舱", "2026-09-09", "值班工程师", 0, "无异常", "35.8℃", "待巡视", 0, None),
        ]
        conn.executemany(
            """
            INSERT INTO patrol
                (record_no, area, patrol_date, inspector, defect_count, infrared_result,
                 terminal_temp, status, abnormal, source_task)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            seed_patrol,
        )


def migrate_legacy_rows(rows: list[dict[str, Any]]) -> None:
    """把过往内存台账回填进数据库。

    - 区域归属沿用原有的「清洗区域」，不重新归类；
    - 老状态按 LEGACY_STATUS_MAP 归并到三态；
    - 计划日期缺失或不是 YYYY-MM-DD 时，按任务 id 回填一个确定日期，保证可按日期检索。
    """
    if not rows:
        return
    fallback_month = "2026-09"
    with connect() as conn:
        existing = {r[0] for r in conn.execute("SELECT task_no FROM cleaning")}
        for row in rows:
            task_no = str(row.get("任务编号") or f"CLEA-LEGACY-{row.get('id')}").strip()
            if task_no in existing:
                continue
            plan_date = str(row.get("计划日期") or "").strip()
            if not _is_date(plan_date):
                legacy_id = int(row.get("id", 0) or 0)
                plan_date = f"{fallback_month}-{min(max(legacy_id, 1), 28):02d}"
            status = LEGACY_STATUS_MAP.get(str(row.get("status") or "").strip(), CLEANING_STATUS_PLAN)
            conn.execute(
                """
                INSERT INTO cleaning
                    (task_no, area, method, plan_date, workers, water_tons, pr_after, status, abnormal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_no,
                    str(row.get("清洗区域") or "未分区").strip(),
                    str(row.get("清洗方式") or "未登记").strip(),
                    plan_date,
                    str(row.get("作业人员") or "").strip(),
                    _to_float(row.get("用水吨数")),
                    _to_float(row.get("清洗后PR值")),
                    status,
                    1 if row.get("abnormal") else 0,
                ),
            )
            existing.add(task_no)


# ---------------------------------------------------------------------------
# 行映射
# ---------------------------------------------------------------------------

def cleaning_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "任务编号": row["task_no"],
        "清洗区域": row["area"],
        "清洗方式": row["method"],
        "计划日期": row["plan_date"],
        "作业人员": row["workers"],
        "用水吨数": row["water_tons"],
        "清洗后PR值": row["pr_after"],
        "清洗状态": row["status"],
        "status": row["status"],
        "pending": row["status"] != CLEANING_STATUS_DONE,
        "abnormal": bool(row["abnormal"]),
    }


def patrol_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "记录编号": row["record_no"],
        "巡视区域": row["area"],
        "巡视日期": row["patrol_date"],
        "巡视人员": row["inspector"],
        "发现缺陷数": row["defect_count"],
        "红外测温结果": row["infrared_result"],
        "接线端子温度": row["terminal_temp"],
        "巡视状态": row["status"],
        "status": row["status"],
        "pending": row["status"] != "已归档",
        "abnormal": bool(row["abnormal"]),
        "source_task": row["source_task"],
        "来源": f"清洗任务 CLEA-{row['source_task']:04d}" if row["source_task"] else "",
    }


# ---------------------------------------------------------------------------
# 组件清洗查询（列表与用水汇总共用的唯一口径）
# ---------------------------------------------------------------------------

def _cleaning_filters(
    *,
    keyword: str | None = None,
    area: str | None = None,
    method: str | None = None,
    plan_date_from: str | None = None,
    plan_date_to: str | None = None,
    status: str | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if keyword:
        clauses.append("task_no LIKE ?")
        params.append(f"%{keyword}%")
    if area:
        clauses.append("area = ?")
        params.append(area)
    if method:
        clauses.append("method = ?")
        params.append(method)
    if plan_date_from:
        clauses.append("plan_date >= ?")
        params.append(plan_date_from)
    if plan_date_to:
        clauses.append("plan_date <= ?")
        params.append(plan_date_to)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def query_cleaning(
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
    where, params = _cleaning_filters(
        keyword=keyword, area=area, method=method,
        plan_date_from=plan_date_from, plan_date_to=plan_date_to, status=status,
    )
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM cleaning {where}", params).fetchone()[0]
        start = max(page - 1, 0) * size
        rows = conn.execute(
            f"SELECT * FROM cleaning {where} ORDER BY plan_date, id LIMIT ? OFFSET ?",
            [*params, size, start],
        ).fetchall()
    return [cleaning_to_dict(row) for row in rows], total


def water_summary(
    *,
    keyword: str | None = None,
    area: str | None = None,
    method: str | None = None,
    plan_date_from: str | None = None,
    plan_date_to: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """按清洗区域汇总用水吨数；筛选条件与列表完全一致，保证数字对得上。"""
    where, params = _cleaning_filters(
        keyword=keyword, area=area, method=method,
        plan_date_from=plan_date_from, plan_date_to=plan_date_to, status=status,
    )
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT area AS 清洗区域,
                   COUNT(*) AS 任务数,
                   ROUND(SUM(water_tons), 2) AS 用水吨数
            FROM cleaning {where}
            GROUP BY area
            ORDER BY 用水吨数 DESC, area
            """,
            params,
        ).fetchall()
    areas = [
        {"清洗区域": row["清洗区域"], "任务数": row["任务数"], "用水吨数": round(row["用水吨数"] or 0.0, 2)}
        for row in rows
    ]
    total_tons = round(sum(item["用水吨数"] for item in areas), 2)
    return {
        "total_tons": total_tons,
        "task_count": sum(item["任务数"] for item in areas),
        "areas": areas,
    }


def cleaning_filter_options() -> dict[str, list[str]]:
    with connect() as conn:
        areas = [r[0] for r in conn.execute("SELECT DISTINCT area FROM cleaning ORDER BY area")]
        methods = [r[0] for r in conn.execute("SELECT DISTINCT method FROM cleaning ORDER BY method")]
    return {"areas": areas, "methods": methods, "statuses": list(CLEANING_STATUSES)}


def find_cleaning(entry_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM cleaning WHERE id = ?", (entry_id,)).fetchone()
    return cleaning_to_dict(row) if row else None


def find_cleaning_by_no(task_no: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM cleaning WHERE task_no = ?", (task_no,)).fetchone()
    return cleaning_to_dict(row) if row else None


def insert_cleaning(values: dict[str, Any]) -> dict[str, Any]:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO cleaning (task_no, area, method, plan_date, workers, water_tons, pr_after, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(values["任务编号"]).strip(),
                str(values["清洗区域"]).strip(),
                str(values["清洗方式"]).strip(),
                str(values.get("计划日期") or "").strip(),
                str(values.get("作业人员") or "").strip(),
                _to_float(values.get("用水吨数")) or 0.0,
                _to_float(values.get("清洗后PR值")),
                CLEANING_STATUS_PLAN,
            ),
        )
        entry_id = cur.lastrowid
    return find_cleaning(entry_id)  # type: ignore[return-value]


def update_cleaning_status(entry_id: int, status: str) -> dict[str, Any]:
    with connect() as conn:
        conn.execute("UPDATE cleaning SET status = ? WHERE id = ?", (status, entry_id))
    return find_cleaning(entry_id)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 巡视查询与「清洗验收待办」联动
# ---------------------------------------------------------------------------

def query_patrol(
    *,
    keyword: str | None = None,
    status: str | None = None,
    source: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    clauses: list[str] = []
    params: list[Any] = []
    if keyword:
        clauses.append("record_no LIKE ?")
        params.append(f"%{keyword}%")
    if status:
        clauses.append("status = ?")
        params.append(status)
    if source == "cleaning":
        clauses.append("source_task IS NOT NULL")
    elif source == "manual":
        clauses.append("source_task IS NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM patrol {where}", params).fetchone()[0]
        start = max(page - 1, 0) * size
        rows = conn.execute(
            f"SELECT * FROM patrol {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, size, start],
        ).fetchall()
    return [patrol_to_dict(row) for row in rows], total


def find_patrol(entry_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM patrol WHERE id = ?", (entry_id,)).fetchone()
    return patrol_to_dict(row) if row else None


def insert_patrol(values: dict[str, Any]) -> dict[str, Any]:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO patrol (record_no, area, patrol_date, inspector, defect_count,
                                infrared_result, terminal_temp, status, source_task)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(values["记录编号"]).strip(),
                str(values["巡视区域"]).strip(),
                str(values.get("巡视日期") or "").strip(),
                str(values.get("巡视人员") or "").strip(),
                int(_to_float(values.get("发现缺陷数")) or 0),
                str(values.get("红外测温结果") or "").strip(),
                str(values.get("接线端子温度") or "").strip(),
                "待巡视",
                values.get("source_task"),
            ),
        )
        entry_id = cur.lastrowid
    return find_patrol(entry_id)  # type: ignore[return-value]


def update_patrol_status(entry_id: int, status: str, abnormal: bool) -> dict[str, Any]:
    with connect() as conn:
        conn.execute(
            "UPDATE patrol SET status = ?, abnormal = ? WHERE id = ?",
            (status, 1 if abnormal else 0, entry_id),
        )
    return find_patrol(entry_id)  # type: ignore[return-value]


def ensure_cleaning_followup(cleaning_entry: dict[str, Any]) -> dict[str, Any]:
    """清洗验收完成后登记一条巡视待办；同一清洗任务重复提交不产生第二条。"""
    source_task = int(cleaning_entry["id"])
    with connect() as conn:
        row = conn.execute("SELECT * FROM patrol WHERE source_task = ?", (source_task,)).fetchone()
        if row is None:
            record_no = f"PATR-C{source_task:04d}"
            conn.execute(
                """
                INSERT INTO patrol (record_no, area, patrol_date, inspector, status, source_task)
                VALUES (?, ?, ?, ?, '待巡视', ?)
                """,
                (record_no, cleaning_entry["清洗区域"], date.today().isoformat(),
                 f"清洗后复核（{cleaning_entry['任务编号']}）", source_task),
            )
            row = conn.execute("SELECT * FROM patrol WHERE source_task = ?", (source_task,)).fetchone()
    return patrol_to_dict(row)


def revoke_cleaning_followup(source_task: int) -> None:
    """已完成的清洗任务退回执行中时，撤销仍处于「待巡视」的联动待办。

    巡视人员已经开始处理（巡视中/已记录/已归档）的记录保留，避免抹掉他人的工作。
    """
    with connect() as conn:
        conn.execute(
            "DELETE FROM patrol WHERE source_task = ? AND status = '待巡视'",
            (source_task,),
        )


# ---------------------------------------------------------------------------
# 概览统计
# ---------------------------------------------------------------------------

def module_counts(module: str) -> dict[str, int]:
    table = "cleaning" if module == "cleaning" else "patrol"
    pending_status = CLEANING_STATUS_DONE if module == "cleaning" else "已归档"
    with connect() as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS created,
                   SUM(CASE WHEN status != ? THEN 1 ELSE 0 END) AS pending,
                   SUM(abnormal) AS abnormal
            FROM {table}
            """,
            (pending_status,),
        ).fetchone()
    return {
        "created": row["created"] or 0,
        "pending": row["pending"] or 0,
        "abnormal": row["abnormal"] or 0,
    }


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False
