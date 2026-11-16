"""经营预测模型接口：维护预测任务，覆盖生成预测、验证结果、归档任务等动作。

预测数据处理接口（观测登记、序列质量、滚动回测、预测结果数据集）也挂在本路由下；
注意这些固定路径必须声明在 ``/{entry_id}`` 之前，否则会被路径参数抢走。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.forecast import ForecastService

router = APIRouter(prefix="/api/forecast", tags=["经营预测模型"])

service = ForecastService()

LIST_FIELDS = ["任务编号", "预测对象", "预测周期", "预测算法", "预测结果", "置信区间", "实际对比", "任务状态"]
STATUSES = ["待预测", "预测中", "已生成", "已验证"]


# ---------------------------------------------------------------------------
# 预测数据处理：观测报告、序列质量、滚动回测
# ---------------------------------------------------------------------------

@router.get("/observations", response_model=PageResult[dict])
def list_observations(
    series: str | None = Query(default=None, description="按序列编号过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """观测报告列表：按可用时间倒序，最新的更正排在前面。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_observations(series=series, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/observations", response_model=ActionResult)
def create_observation(payload: EntryPayload) -> ActionResult:
    """登记观测报告；同一观测日期再次登记即形成更正版本，历史回测截点不会被回填。"""
    row, errors = service.create_observation(payload.values)
    if errors:
        return ActionResult(ok=False, message=f"观测登记失败：{'、'.join(errors)}")
    return ActionResult(ok=True, message="观测报告已登记；如为更正版本，将在下次回测形成新预测版本", entry=row)


@router.get("/series")
def list_series() -> dict[str, Any]:
    """序列质量摘要：缺期、连续缺期、迟到更正、全零与短序列标记。"""
    return {"items": service.list_series()}


@router.post("/backtests", response_model=ActionResult)
def run_backtest(payload: EntryPayload) -> ActionResult:
    """执行滚动回测；相同配置与数据截面幂等复用，新更正只形成新版本。"""
    run, message, reused = service.run_backtest(payload.values)
    if run is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry={"id": run["id"], "版本号": run["版本号"], "复用": reused})


@router.get("/backtests")
def list_backtests() -> dict[str, Any]:
    """回测版本清单：每次回测一个版本，历史版本保持完整。"""
    return {"items": service.list_backtests()}


@router.get("/backtests/{run_id}")
def get_backtest(run_id: int) -> dict[str, Any]:
    """回测版本明细：各时间折覆盖情况、按预测起点分组的预测点、数据质量与未来样本检查。"""
    run = service.get_backtest(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"回测版本 {run_id} 不存在")
    return run


# ---------------------------------------------------------------------------
# 预测任务清单（原有 CRUD 与状态流转）
# ---------------------------------------------------------------------------

@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出经营预测模型清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "forecast", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    status: str | None = Query(default=None, description="待预测、预测中、已生成、已验证"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按任务编号与状态过滤经营预测模型列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条预测任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"预测任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条预测任务，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="预测任务已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条预测任务执行生成预测、验证结果、归档任务；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
