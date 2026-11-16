"""经营预测模型业务规则：状态流转、字段校验与筛选口径都收在这里。

预测数据处理部分（观测登记、序列清洗、滚动回测、预测结果数据集）也收在本模块：
- 观测报告带「观测日期 + 可用时间」双时间轴，同一观测日期再次登记即形成更正版本；
- 回测按截点可见性取数，新更正只会形成新预测版本，历史版本保持不变；
- 回测结果先整体算完再一次落库，中断不会留下半个版本，重试幂等复用已完成版本。
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from app.services import forecast_engine as engine
from app.store import store

MODULE = "forecast"
REQUIRED_FIELDS = ["任务编号", "预测对象", "预测周期"]
STATUS_ORDER = ["待预测", "预测中", "已生成", "已验证"]
ACTION_RULES = {"生成预测": "待预测", "验证结果": "已生成", "归档任务": "已验证"}
NEGATIVE_ACTIONS = []

SERIES_META = {
    "SER-0001": "月度营业收入（万元）",
    "SER-0002": "新开门店月销售（万元）",
    "SER-0003": "停业门店月销售（万元）",
    "SER-0004": "采集不稳定序列（万元）",
}

_SEASONAL = [0, -18, -5, 4, 6, 10, 12, 8, 5, 7, 9, 15]


def _month_axis(start_year: int, start_month: int, count: int) -> list[tuple[int, int]]:
    axis: list[tuple[int, int]] = []
    year, month = start_year, start_month
    for _ in range(count):
        axis.append((year, month))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return axis


def _avail_next_month(year: int, month: int) -> str:
    """月度报告次月 5 日上午到账。"""
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return f"{next_year:04d}-{next_month:02d}-05T09:00:00"


def _seed_observations() -> list[dict[str, Any]]:
    """示例观测：覆盖迟到更正、节假日停业零值、采集遗漏、连续缺期、全零与短序列。"""
    rows: list[dict[str, Any]] = []

    def add(series: str, day: str, value: float | None, avail: str, rtype: str = "正常") -> None:
        rows.append({
            "id": len(rows) + 1,
            "序列编号": series,
            "观测日期": day,
            "数值": value,
            "可用时间": avail,
            "记录类型": rtype,
        })

    # SER-0001 月度营业收入：2024-01 .. 2026-10，含节假日停业、采集遗漏与两次迟到更正
    for index, (year, month) in enumerate(_month_axis(2024, 1, 34)):
        day = f"{year:04d}-{month:02d}-01"
        avail = _avail_next_month(year, month)
        if (year, month) == (2025, 2):
            add("SER-0001", day, 0.0, avail, "节假日停业")  # 春节停业：真实零值
            continue
        if (year, month) == (2026, 3):
            add("SER-0001", day, None, avail, "采集遗漏")  # 缺报：保留缺期，不补零
            continue
        value = round(100 + 2.5 * index + _SEASONAL[month - 1], 1)
        add("SER-0001", day, value, avail)
        if (year, month) == (2025, 6):
            # 迟到更正：初值 7 月到账，更正值 10 月才到账
            add("SER-0001", day, value + 12.0, "2025-10-12T09:00:00")
        if (year, month) == (2026, 8):
            add("SER-0001", day, value + 6.0, "2026-10-08T09:00:00")

    # SER-0002 短序列：2026-05 .. 2026-10，有效样本不足最小训练样本
    for index, (year, month) in enumerate(_month_axis(2026, 5, 6)):
        add(
            "SER-0002", f"{year:04d}-{month:02d}-01",
            round(30 + 3 * index + _SEASONAL[month - 1] * 0.2, 1),
            _avail_next_month(year, month),
        )

    # SER-0003 全零序列：2025-01 .. 2026-10，长期未营业
    for year, month in _month_axis(2025, 1, 22):
        add("SER-0003", f"{year:04d}-{month:02d}-01", 0.0, _avail_next_month(year, month))

    # SER-0004 连续缺期：2025-01 .. 2026-10，其中 2025-07/08/09 连续采集遗漏
    for index, (year, month) in enumerate(_month_axis(2025, 1, 22)):
        day = f"{year:04d}-{month:02d}-01"
        avail = _avail_next_month(year, month)
        if (year, month) in ((2025, 7), (2025, 8), (2025, 9)):
            add("SER-0004", day, None, avail, "采集遗漏")
        else:
            add("SER-0004", day, round(60 + 1.5 * index + _SEASONAL[month - 1] * 0.5, 1), avail)
    return rows


class ForecastDataStore:
    """预测数据处理专用存储：观测报告与回测版本，与通用业务表分开管理。"""

    def __init__(self) -> None:
        self.observations: list[dict[str, Any]] = _seed_observations()
        self.runs: list[dict[str, Any]] = []

    def next_observation_id(self) -> int:
        return max((int(row["id"]) for row in self.observations), default=0) + 1

    def next_run_id(self) -> int:
        return max((int(row["id"]) for row in self.runs), default=0) + 1


data_store = ForecastDataStore()


def get_backtest_run(run_id: int) -> dict[str, Any] | None:
    """供跨模块（同期对比分析）读取预测结果数据集。"""
    for run in data_store.runs:
        if int(run["id"]) == run_id:
            return run
    return None


def list_backtest_runs() -> list[dict[str, Any]]:
    return list(data_store.runs)


class ForecastService:
    # ------------------------------------------------------------------
    # 预测任务登记（原有 CRUD 与状态流转）
    # ------------------------------------------------------------------
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
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
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
            return None, f"预测任务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于经营预测模型可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"预测任务已{action}"

    # ------------------------------------------------------------------
    # 观测报告：登记、查询与序列质量摘要
    # ------------------------------------------------------------------
    def list_observations(
        self,
        *,
        series: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = sorted(data_store.observations, key=lambda row: (row["可用时间"], row["id"]), reverse=True)
        if series:
            rows = [row for row in rows if row["序列编号"] == series]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def create_observation(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """登记一条观测报告；同一观测日期再次登记即形成更正版本。"""
        errors: list[str] = []
        series = str(values.get("序列编号") or "").strip()
        if not series:
            errors.append("序列编号不能为空")
        day_text = str(values.get("观测日期") or "").strip()
        try:
            day = engine.parse_day(day_text)
        except (TypeError, ValueError):
            errors.append("观测日期须为 YYYY-MM-DD")
            day = None
        record_type = str(values.get("记录类型") or "正常").strip()
        if record_type not in engine.RECORD_TYPES:
            errors.append(f"记录类型须为 {'/'.join(engine.RECORD_TYPES)}")

        value: float | None = None
        if record_type == "采集遗漏":
            # 缺报没有数值，强制为空，绝不按零处理
            value = None
        else:
            raw_value = values.get("数值")
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                errors.append("数值须为数字")
                value = None
            if record_type == "节假日停业" and value not in (None, 0.0):
                errors.append("节假日停业的观测值只能为 0")

        avail_text = str(values.get("可用时间") or "").strip()
        if avail_text:
            try:
                parsed = datetime.fromisoformat(avail_text)
            except ValueError:
                errors.append("可用时间须为 ISO 格式（如 2026-01-05T09:00:00）")
                parsed = None
            if parsed is not None and parsed.tzinfo is not None:
                errors.append("可用时间不要带时区，按本地时间登记")
                parsed = None
            avail = parsed.isoformat(timespec="seconds") if parsed else ""
        else:
            avail = datetime.now().isoformat(timespec="seconds")

        if errors:
            return None, errors
        row = {
            "id": data_store.next_observation_id(),
            "序列编号": series,
            "观测日期": day.isoformat() if day else day_text,
            "数值": value,
            "可用时间": avail,
            "记录类型": record_type,
        }
        data_store.observations.append(row)
        return row, []

    def list_series(self) -> list[dict[str, Any]]:
        """序列质量摘要：期数、有效值、缺期、连续缺期、迟到更正、全零与短序列标记。"""
        summaries: list[dict[str, Any]] = []
        series_ids = sorted({row["序列编号"] for row in data_store.observations})
        for series_id in series_ids:
            reports = [
                engine.normalize_report(row, "月")
                for row in data_store.observations
                if row["序列编号"] == series_id
            ]
            quality = engine.data_quality(reports, engine.BacktestConfig(序列编号=series_id))
            summaries.append({
                "序列编号": series_id,
                "序列名称": SERIES_META.get(series_id, series_id),
                "报告数": len(reports),
                "有效值数": quality["有效值数"],
                "缺期总数": quality["缺期总数"],
                "最长连续缺期": quality["连续缺期"],
                "迟到更正数": quality["迟到更正数"],
                "全零序列": quality["全零序列"],
                "短序列": quality["短序列"],
                "最新可用时间": max((report["avail"] for report in reports), default=None),
            })
        return summaries

    # ------------------------------------------------------------------
    # 滚动回测：版本化预测结果数据集
    # ------------------------------------------------------------------
    def run_backtest(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
        """执行滚动回测。返回 (版本记录, 提示信息, 是否复用已有版本)。"""
        config, errors = engine.parse_config(values)
        if config is None:
            return None, "、".join(errors), False
        now = datetime.now().isoformat(timespec="seconds")
        raw_reports = [
            row for row in data_store.observations
            if row["序列编号"] == config.序列编号 and row["可用时间"] <= now
        ]
        if not raw_reports:
            return None, f"序列 {config.序列编号} 当前没有任何可见观测报告", False
        reports = [engine.normalize_report(row, config.频率) for row in raw_reports]
        snapshot = max(report["avail"] for report in reports)
        digest = engine.fingerprint(config, reports)

        # 幂等：相同配置与数据截面的完整版本直接复用，中断后重试不会重复或覆盖
        for run in data_store.runs:
            if run["配置指纹"] == digest and run["状态"] == "完成":
                return run, f"相同配置与数据截面的回测已存在，复用{run['版本号']}；新更正会形成新版本", True

        # 纯计算全部完成后才落库：中断不会留下半个版本，历史版本保持完整
        result = engine.run_backtest(reports, config, now)
        run_id = data_store.next_run_id()
        run = {
            "id": run_id,
            "版本号": f"V{run_id}",
            "序列编号": config.序列编号,
            "状态": "完成",
            "创建时间": now,
            "数据截面时间": snapshot,
            "配置": asdict(config),
            "配置指纹": digest,
            **result,
        }
        data_store.runs.append(run)
        evaluated = sum(item["有效样本数"] for item in result["算法汇总"])
        return run, f"滚动回测完成，生成{run['版本号']}：{len(result['folds'])} 个时间折，有效核对样本 {evaluated} 个", False

    def list_backtests(self) -> list[dict[str, Any]]:
        """版本清单（不含逐折明细，明细走 get_backtest）。"""
        summaries: list[dict[str, Any]] = []
        for run in sorted(data_store.runs, key=lambda item: item["id"], reverse=True):
            summaries.append({
                "id": run["id"],
                "版本号": run["版本号"],
                "序列编号": run["序列编号"],
                "状态": run["状态"],
                "创建时间": run["创建时间"],
                "数据截面时间": run["数据截面时间"],
                "配置": run["配置"],
                "时间折数": len(run["folds"]),
                "预测点数": len(run["points"]),
            })
        return summaries

    def get_backtest(self, run_id: int) -> dict[str, Any] | None:
        return get_backtest_run(run_id)
