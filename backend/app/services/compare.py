"""同期对比分析业务规则：状态流转、字段校验与筛选口径都收在这里。

跨模块核对：读取经营预测模型的预测结果数据集，按实际发生日期关联最终实际值，
核对预测值与实际值；实际尚未到达的点标为待观测，不按零误差处理。
"""
from __future__ import annotations

from typing import Any

from app.services.forecast import get_backtest_run, list_backtest_runs
from app.store import store

MODULE = "compare"
REQUIRED_FIELDS = ["方案编号", "对比指标", "基准周期"]
STATUS_ORDER = ["草稿", "已对比", "已分析", "已归档"]
ACTION_RULES = {"执行对比": "草稿", "原因分析": "已对比", "归档方案": "已分析"}
NEGATIVE_ACTIONS = []


class CompareService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("方案编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
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
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"对比方案 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于同期对比分析可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"对比方案已{action}"

    # ------------------------------------------------------------------
    # 跨模块核对：读取预测结果数据集，关联实际发生日期
    # ------------------------------------------------------------------
    def list_forecast_runs(self) -> list[dict[str, Any]]:
        """可供核对的预测版本清单（来自经营预测模型的预测结果数据集）。"""
        return [
            {
                "id": run["id"],
                "版本号": run["版本号"],
                "序列编号": run["序列编号"],
                "状态": run["状态"],
                "创建时间": run["创建时间"],
                "数据截面时间": run["数据截面时间"],
            }
            for run in sorted(list_backtest_runs(), key=lambda item: item["id"], reverse=True)
        ]

    def forecast_check(self, run_id: int) -> dict[str, Any] | None:
        """核对视图：逐预测点关联实际发生日期的最终实际值，并汇总数据质量检查。

        每个预测点保留训练截止、输入可用时间、所用算法与误差分母；
        实际尚未到达的点标为待观测，不参与误差统计。
        """
        run = get_backtest_run(run_id)
        if run is None:
            return None
        items: list[dict[str, Any]] = []
        for point in run["points"]:
            items.append({
                "折序号": point["折序号"],
                "预测起点": point["预测起点"],
                "训练截止期": point["训练截止期"],
                "输入可用时间": point["截点可用时间"],
                "目标期": point["目标期"],
                "算法名称": point["算法名称"],
                "预测值": point["预测值"],
                "区间下限": point["区间下限"],
                "区间上限": point["区间上限"],
                "实际值": point["实际值"],
                "实际可用时间": point["实际可用时间"],
                "误差": point["误差"],
                "相对误差": point["相对误差"],
                "误差分母": point["误差分母"],
                "核对状态": point["核对状态"],
                "剔除原因": point["剔除原因"],
            })
        quality = run["数据质量"]
        return {
            "版本号": run["版本号"],
            "序列编号": run["序列编号"],
            "创建时间": run["创建时间"],
            "数据截面时间": run["数据截面时间"],
            "items": items,
            "摘要": {
                "预测点数": len(items),
                "已核对数": sum(1 for item in items if item["核对状态"] == "已核对"),
                "待观测数": sum(1 for item in items if item["核对状态"] == "待观测"),
                "剔除数": sum(1 for item in items if item["核对状态"] == "已剔除"),
                "迟到更正": quality["迟到更正"],
                "迟到更正数": quality["迟到更正数"],
                "连续缺期": quality["连续缺期"],
                "缺期总数": quality["缺期总数"],
                "全零序列": quality["全零序列"],
                "短序列": quality["短序列"],
                "未来样本检查": run["未来样本检查"],
            },
        }
