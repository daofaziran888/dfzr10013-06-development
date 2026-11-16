"""同期对比分析接口：维护对比方案，覆盖执行对比、原因分析、归档方案等动作。

跨模块核对接口（读取经营预测模型的预测结果数据集）也挂在本路由下；
固定路径须声明在 ``/{entry_id}`` 之前，避免被路径参数抢走。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.compare import CompareService

router = APIRouter(prefix="/api/compare", tags=["同期对比分析"])

service = CompareService()

LIST_FIELDS = ["方案编号", "对比指标", "基准周期", "对比周期", "变化幅度", "变化方向", "原因分析", "方案状态"]
STATUSES = ["草稿", "已对比", "已分析", "已归档"]


@router.get("/forecast-runs")
def forecast_runs() -> dict[str, Any]:
    """可供核对的预测版本清单（来自经营预测模型的预测结果数据集）。"""
    return {"items": service.list_forecast_runs()}


@router.get("/forecast-check/{run_id}")
def forecast_check(run_id: int) -> dict[str, Any]:
    """预测核对视图：按实际发生日期关联最终实际值，未到达的点标为待观测。"""
    result = service.forecast_check(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"预测版本 {run_id} 不存在，请先在经营预测模型模块运行回测")
    return result


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出同期对比分析清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "compare", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按方案编号检索"),
    status: str | None = Query(default=None, description="草稿、已对比、已分析、已归档"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按方案编号与状态过滤同期对比分析列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条对比方案明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"对比方案 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条对比方案，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="对比方案已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条对比方案执行执行对比、原因分析、归档方案；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
