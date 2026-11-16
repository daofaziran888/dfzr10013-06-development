"""经营预测数据处理引擎：序列清洗、滚动回测、区间估计与误差核对。

设计约束（与业务约定一一对应）：

- 观测带「观测日期」与「可用时间」双时间轴。回测截点只能看到
  ``可用时间 <= 截点时间`` 且 ``观测期 <= 训练截止期`` 的报告；截点时间取各期
  首版报告可用时间的最大值（预测发生时刻），事后更正不会回填到更早的截点，
  避免用最终修订值污染历史截面（未来信息泄露）。
- 缺期（未上报 / 采集遗漏）保留为缺期，绝不默认填零；节假日停业的零值是真实观测，
  与采集遗漏含义不同，分开标记。
- 预测区间来自训练窗内、同算法同步长残差的分位数，可核验；残差样本不足时明确
  不提供区间，不给固定百分比。
- 误差只在实际值已到达的点上计算；实际尚未到达的点标记为「待观测」，不按零误差处理。
- 引擎为纯函数：输入观测报告与配置，输出完整回测结果，不触碰任何存储。
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

FREQUENCIES = ("日", "周", "月")
RECORD_TYPES = ("正常", "节假日停业", "采集遗漏")
ALGORITHMS = ("naive", "moving_average", "seasonal_naive")
ALGORITHM_LABELS = {
    "naive": "朴素法（上一期值）",
    "moving_average": "移动平均",
    "seasonal_naive": "季节朴素",
}

# 周期状态
PERIOD_VALID = "有效"
PERIOD_HOLIDAY = "节假日停业"
PERIOD_MISSING = "缺期"

# 核对状态
CHECK_EVALUATED = "已核对"
CHECK_PENDING = "待观测"
CHECK_EXCLUDED = "已剔除"


# ---------------------------------------------------------------------------
# 周期频率：周期键的规范化与步进
# ---------------------------------------------------------------------------

def parse_day(text: str) -> date:
    return datetime.strptime(str(text)[:10], "%Y-%m-%d").date()


def period_key(day: date, freq: str) -> str:
    """把某个自然日归并到所属周期键；周期键按字典序即可比较先后。"""
    if freq == "日":
        return day.isoformat()
    if freq == "周":
        iso = day.isocalendar()
        return f"{iso.year:04d}-W{iso.week:02d}"
    if freq == "月":
        return f"{day.year:04d}-{day.month:02d}"
    raise ValueError(f"不支持的周期频率：{freq}")


def period_start(key: str, freq: str) -> date:
    if freq == "日":
        return parse_day(key)
    if freq == "周":
        year, week = key.split("-W")
        return date.fromisocalendar(int(year), int(week), 1)
    if freq == "月":
        year, month = key.split("-")
        return date(int(year), int(month), 1)
    raise ValueError(f"不支持的周期频率：{freq}")


def add_periods(key: str, freq: str, n: int) -> str:
    """周期键向前（n>0）或向后（n<0）平移 n 个周期。"""
    if freq == "日":
        return (parse_day(key) + timedelta(days=n)).isoformat()
    if freq == "周":
        shifted = period_start(key, freq) + timedelta(weeks=n)
        iso = shifted.isocalendar()
        return f"{iso.year:04d}-W{iso.week:02d}"
    if freq == "月":
        year, month = key.split("-")
        total = int(year) * 12 + (int(month) - 1) + n
        return f"{total // 12:04d}-{total % 12 + 1:02d}"
    raise ValueError(f"不支持的周期频率：{freq}")


def build_grid(start_key: str, end_key: str, freq: str) -> list[str]:
    """生成 [start_key, end_key] 的连续周期网格；start 晚于 end 时为空。"""
    keys: list[str] = []
    current = start_key
    guard = 0
    while current <= end_key and guard < 4000:
        keys.append(current)
        current = add_periods(current, freq, 1)
        guard += 1
    return keys


# ---------------------------------------------------------------------------
# 观测清洗：截点可见性、缺期与零值的区分
# ---------------------------------------------------------------------------

def normalize_report(raw: dict[str, Any], freq: str) -> dict[str, Any]:
    """把存储层的观测报告规范成引擎内部结构，并按频率归并观测期。"""
    value = raw.get("数值")
    return {
        "period": period_key(parse_day(str(raw.get("观测日期") or "")), freq),
        "value": None if value is None else float(value),
        "avail": str(raw.get("可用时间") or ""),
        "rtype": str(raw.get("记录类型") or "正常"),
    }


def latest_by_period(reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """每个观测期只保留可用时间最晚的一版报告（最终可见修订）。"""
    latest: dict[str, dict[str, Any]] = {}
    for report in reports:
        current = latest.get(report["period"])
        if current is None or report["avail"] >= current["avail"]:
            latest[report["period"]] = report
    return latest


def clean_series(visible: list[dict[str, Any]], freq: str, origin_key: str) -> list[dict[str, Any]]:
    """把截点可见的报告整理成连续周期网格。

    缺期（没有可见报告，或可见报告是采集遗漏）保留为缺期，不填零；
    节假日停业是真实零值，与缺期分开标记。
    """
    if not visible:
        return []
    first = min(report["period"] for report in visible)
    grid = build_grid(first, origin_key, freq)
    latest = latest_by_period(visible)
    version_count: dict[str, int] = {}
    for report in visible:
        version_count[report["period"]] = version_count.get(report["period"], 0) + 1
    states: list[dict[str, Any]] = []
    for key in grid:
        report = latest.get(key)
        if report is None or report["rtype"] == "采集遗漏":
            states.append({
                "观测期": key, "状态": PERIOD_MISSING, "数值": None,
                "可用时间": report["avail"] if report else None,
                "版本数": version_count.get(key, 0),
            })
        elif report["rtype"] == "节假日停业":
            states.append({
                "观测期": key, "状态": PERIOD_HOLIDAY, "数值": 0.0,
                "可用时间": report["avail"], "版本数": version_count.get(key, 0),
            })
        else:
            states.append({
                "观测期": key, "状态": PERIOD_VALID, "数值": float(report["value"]),
                "可用时间": report["avail"], "版本数": version_count.get(key, 0),
            })
    return states


def longest_missing_run(states: list[dict[str, Any]]) -> int:
    """连续缺期的最长段长度。"""
    longest = current = 0
    for state in states:
        if state["状态"] == PERIOD_MISSING:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


# ---------------------------------------------------------------------------
# 基线算法：全部跳过缺期，绝不把缺报当零
# ---------------------------------------------------------------------------

def _valid_tail(values: list[float | None], count: int) -> list[float]:
    """取序列末尾 count 个有效值（保持原顺序），缺期直接跳过。"""
    picked: list[float] = []
    for value in reversed(values):
        if value is None:
            continue
        picked.append(value)
        if len(picked) == count:
            break
    picked.reverse()
    return picked


def forecast_point(
    algorithm: str,
    values: list[float | None],
    *,
    horizon: int,
    window: int,
    season: int,
) -> float | None:
    """用训练窗内的有效值预测第 horizon 步；无法出值时返回 None。"""
    if algorithm == "naive":
        tail = _valid_tail(values, 1)
        return tail[-1] if tail else None
    if algorithm == "moving_average":
        tail = _valid_tail(values, window)
        if len(tail) < 2:
            return None
        return sum(tail) / len(tail)
    if algorithm == "seasonal_naive":
        # 目标期下标 = len(values) - 1 + horizon；向回找同相位最近的有效值
        back = len(values) - 1 + horizon - season
        while back >= 0:
            value = values[back]
            if value is not None:
                return value
            back -= season
        return None
    raise ValueError(f"未知算法：{algorithm}")


def training_residuals(
    algorithm: str,
    values: list[float | None],
    *,
    horizon: int,
    window: int,
    season: int,
    min_train: int,
) -> list[float]:
    """训练窗内同步长伪样本外残差（实际 - 预测），是预测区间的统计依据。"""
    residuals: list[float] = []
    for end in range(min_train, len(values) - horizon + 1):
        estimate = forecast_point(
            algorithm, values[:end], horizon=horizon, window=window, season=season,
        )
        actual = values[end - 1 + horizon]
        if estimate is None or actual is None:
            continue
        residuals.append(actual - estimate)
    return residuals


def quantile(sorted_values: list[float], q: float) -> float | None:
    """线性插值分位数；输入必须已排序。"""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return sorted_values[low]
    fraction = position - low
    return sorted_values[low] * (1 - fraction) + sorted_values[high] * fraction


# ---------------------------------------------------------------------------
# 回测配置
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BacktestConfig:
    序列编号: str
    频率: str = "月"
    预测步长: int = 1
    算法: tuple[str, ...] = ALGORITHMS
    折数: int = 6
    移动平均窗口: int = 3
    季节周期: int = 12
    最小训练样本: int = 8
    置信水平: float = 0.9
    最小残差样本: int = 5


def parse_config(values: dict[str, Any]) -> tuple[BacktestConfig | None, list[str]]:
    """把接口入参解析成回测配置；任何一项不合法都明确报错，不静默用默认值。"""
    errors: list[str] = []
    series = str(values.get("序列编号") or "").strip()
    if not series:
        errors.append("序列编号不能为空")
    freq = str(values.get("频率") or "月").strip()
    if freq not in FREQUENCIES:
        errors.append(f"周期频率须为 {'/'.join(FREQUENCIES)}")

    def _int(field_name: str, default: int, low: int, high: int) -> int:
        raw = values.get(field_name)
        if raw is None or raw == "":
            return default
        try:
            number = int(raw)
        except (TypeError, ValueError):
            errors.append(f"{field_name}须为整数")
            return default
        if not low <= number <= high:
            errors.append(f"{field_name}须在 {low}~{high} 之间")
        return number

    horizon = _int("预测步长", 1, 1, 12)
    folds = _int("折数", 6, 1, 24)
    window = _int("移动平均窗口", 3, 2, 12)
    season = _int("季节周期", 12, 2, 24)
    min_train = _int("最小训练样本", 8, 2, 60)
    min_resid = _int("最小残差样本", 5, 3, 60)

    raw_level = values.get("置信水平")
    level = 0.9 if raw_level in (None, "") else None
    if level is None:
        try:
            level = float(raw_level)
        except (TypeError, ValueError):
            errors.append("置信水平须为 0.5~0.99 之间的小数")
            level = 0.9
    if not 0.5 <= level <= 0.99:
        errors.append("置信水平须在 0.5~0.99 之间")

    raw_algos = values.get("算法")
    if raw_algos in (None, "", []):
        algorithms: tuple[str, ...] = ALGORITHMS
    else:
        if isinstance(raw_algos, str):
            raw_algos = [item.strip() for item in raw_algos.split(",") if item.strip()]
        unknown = [item for item in raw_algos if item not in ALGORITHMS]
        if unknown:
            errors.append(f"未知算法：{'、'.join(unknown)}")
        algorithms = tuple(item for item in raw_algos if item in ALGORITHMS)
        if not algorithms:
            errors.append("至少选择一种基线算法")

    if errors:
        return None, errors
    return BacktestConfig(
        序列编号=series, 频率=freq, 预测步长=horizon, 算法=algorithms, 折数=folds,
        移动平均窗口=window, 季节周期=season, 最小训练样本=min_train,
        置信水平=level, 最小残差样本=min_resid,
    ), []


def fingerprint(config: BacktestConfig, reports: list[dict[str, Any]]) -> str:
    """配置 + 数据截面的指纹：新更正会改变指纹，从而形成新预测版本。"""
    payload = {
        "配置": asdict(config),
        "报告数": len(reports),
        "最大可用时间": max((report["avail"] for report in reports), default=""),
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 滚动回测
# ---------------------------------------------------------------------------

def _latest_actual(reports: list[dict[str, Any]], target: str, now: str) -> dict[str, Any] | None:
    """目标期的最终可见实际值（仅用于评估，绝不进入训练）。"""
    candidates = [r for r in reports if r["period"] == target and r["avail"] <= now]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["avail"])


def run_backtest(
    reports: list[dict[str, Any]],
    config: BacktestConfig,
    now: str,
) -> dict[str, Any]:
    """滚动回测主流程：逐截点清洗可见序列、逐算法出预测并与最终实际值核对。"""
    periods = sorted({report["period"] for report in reports})
    grid = build_grid(periods[0], periods[-1], config.频率)
    origins = grid[max(0, len(grid) - config.折数):]

    # 每个观测期首版报告的可用时间：预测发生时刻由数据到齐时间决定，
    # 迟到更正不会把截点往后推，也不会回填到更早的截点。
    first_avail: dict[str, str] = {}
    for report in reports:
        current = first_avail.get(report["period"])
        if current is None or report["avail"] < current:
            first_avail[report["period"]] = report["avail"]

    folds: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []
    for index, origin in enumerate(origins, start=1):
        # 截点可见性：观测期不晚于训练截止期，且报告可用时间不晚于截点时间。
        # 截点时间 = 截止期之前各期首版报告可用时间的最大值，即预测发生的时刻。
        known_at = [avail for period, avail in first_avail.items() if period <= origin]
        as_of = max(known_at)
        visible = [r for r in reports if r["period"] <= origin and r["avail"] <= as_of]
        states = clean_series(visible, config.频率, origin)
        values = [s["数值"] if s["状态"] != PERIOD_MISSING else None for s in states]
        valid_count = sum(1 for v in values if v is not None)
        target = add_periods(origin, config.频率, config.预测步长)

        fold = {
            "折序号": index,
            "训练截止期": origin,
            "目标期": target,
            "截点可用时间": as_of,
            "训练起始期": states[0]["观测期"] if states else None,
            "有效训练样本数": valid_count,
            "缺期数": len(values) - valid_count,
            "训练覆盖率": round(valid_count / len(values), 4) if values else 0.0,
            "最长连续缺期": longest_missing_run(states),
            "训练最大观测期": states[-1]["观测期"] if states else None,
            "训练最大可用时间": max((s["可用时间"] for s in states if s["可用时间"]), default=None),
            "状态": "完成",
            "剔除原因": None,
            # 保存截点可见的观测快照，供逐折核对，不回填后续更正
            "可见观测": states,
        }
        if valid_count < config.最小训练样本:
            fold["状态"] = "已剔除"
            fold["剔除原因"] = (
                f"训练样本不足：有效 {valid_count} 期 < 最小训练样本 "
                f"{config.最小训练样本} 期（短序列，缺期不补零）"
            )
            folds.append(fold)
            continue

        actual_report = _latest_actual(reports, target, now)
        for algorithm in config.算法:
            estimate = forecast_point(
                algorithm, values,
                horizon=config.预测步长, window=config.移动平均窗口, season=config.季节周期,
            )
            point = {
                "折序号": index,
                "预测起点": origin,
                "训练截止期": origin,
                "截点可用时间": as_of,
                "目标期": target,
                "算法": algorithm,
                "算法名称": ALGORITHM_LABELS[algorithm],
                "预测值": None,
                "区间下限": None,
                "区间上限": None,
                "区间依据": None,
                "残差样本数": 0,
                "实际值": None,
                "实际可用时间": None,
                "误差": None,
                "绝对误差": None,
                "相对误差": None,
                "误差分母": None,
                "区间命中": None,
                "核对状态": CHECK_PENDING,
                "剔除原因": None,
            }
            if estimate is None:
                point["核对状态"] = CHECK_EXCLUDED
                point["剔除原因"] = "该算法在当前训练窗内无法出值（历史有效值不足）"
                points.append(point)
                continue
            point["预测值"] = round(estimate, 4)

            residuals = training_residuals(
                algorithm, values,
                horizon=config.预测步长, window=config.移动平均窗口,
                season=config.季节周期, min_train=config.最小训练样本,
            )
            point["残差样本数"] = len(residuals)
            if len(residuals) >= config.最小残差样本:
                tail_q = (1 - config.置信水平) / 2
                ordered = sorted(residuals)
                lower = estimate + (quantile(ordered, tail_q) or 0.0)
                upper = estimate + (quantile(ordered, 1 - tail_q) or 0.0)
                point["区间下限"] = round(lower, 4)
                point["区间上限"] = round(upper, 4)
                point["区间依据"] = (
                    f"训练窗内{config.预测步长}步残差分位数"
                    f"（n={len(residuals)}，置信水平{config.置信水平}）"
                )
            else:
                point["区间依据"] = (
                    f"残差样本不足（{len(residuals)}<{config.最小残差样本}），不提供预测区间"
                )

            if actual_report is None or actual_report["rtype"] == "采集遗漏":
                # 实际尚未到达（或最终仍是缺报）：标待观测，不按零误差处理
                point["核对状态"] = CHECK_PENDING
            else:
                actual = 0.0 if actual_report["rtype"] == "节假日停业" else float(actual_report["value"])
                error = estimate - actual
                point["实际值"] = actual
                point["实际可用时间"] = actual_report["avail"]
                point["误差"] = round(error, 4)
                point["绝对误差"] = round(abs(error), 4)
                point["误差分母"] = actual
                if actual != 0:
                    point["相对误差"] = round(abs(error) / abs(actual), 4)
                point["核对状态"] = CHECK_EVALUATED
                if point["区间下限"] is not None:
                    point["区间命中"] = bool(point["区间下限"] <= actual <= point["区间上限"])
            points.append(point)
        folds.append(fold)

    return {
        "folds": folds,
        "points": points,
        "算法汇总": summarize_by_algorithm(points, config),
        "数据质量": data_quality(reports, config),
        "未来样本检查": audit_no_future_samples(folds, points),
    }


def summarize_by_algorithm(points: list[dict[str, Any]], config: BacktestConfig) -> list[dict[str, Any]]:
    """按算法汇总：相同截点与步长下比较误差，同时报告有效样本数与覆盖情况。"""
    summaries: list[dict[str, Any]] = []
    for algorithm in config.算法:
        subset = [p for p in points if p["算法"] == algorithm]
        evaluated = [p for p in subset if p["核对状态"] == CHECK_EVALUATED]
        relatives = [p["相对误差"] for p in evaluated if p["相对误差"] is not None]
        with_interval = [p for p in evaluated if p["区间下限"] is not None]
        hits = [p for p in with_interval if p["区间命中"]]
        mae = None
        if evaluated:
            mae = round(sum(p["绝对误差"] for p in evaluated) / len(evaluated), 4)
        summaries.append({
            "算法": algorithm,
            "算法名称": ALGORITHM_LABELS[algorithm],
            "预测点数": len(subset),
            "有效样本数": len(evaluated),
            "待观测数": sum(1 for p in subset if p["核对状态"] == CHECK_PENDING),
            "剔除数": sum(1 for p in subset if p["核对状态"] == CHECK_EXCLUDED),
            "MAE": mae,
            "平均相对误差": round(sum(relatives) / len(relatives), 4) if relatives else None,
            "区间覆盖率": round(len(hits) / len(with_interval), 4) if with_interval else None,
            "区间提供率": (
                round(sum(1 for p in subset if p["区间下限"] is not None) / len(subset), 4)
                if subset else None
            ),
        })
    return summaries


def data_quality(reports: list[dict[str, Any]], config: BacktestConfig) -> dict[str, Any]:
    """数据质量核对：迟到更正、连续缺期、全零序列、短序列。"""
    last_period = max(report["period"] for report in reports)
    states = clean_series(reports, config.频率, last_period)
    valid_values = [s["数值"] for s in states if s["状态"] != PERIOD_MISSING]
    versions: dict[str, list[str]] = {}
    for report in reports:
        versions.setdefault(report["period"], []).append(report["avail"])
    late_corrections = [
        {
            "观测期": period,
            "版本数": len(avails),
            "首次可用时间": min(avails),
            "末次可用时间": max(avails),
        }
        for period, avails in sorted(versions.items())
        if len(avails) > 1
    ]
    return {
        "迟到更正": late_corrections,
        "迟到更正数": len(late_corrections),
        "缺期总数": sum(1 for s in states if s["状态"] == PERIOD_MISSING),
        "连续缺期": longest_missing_run(states),
        "全零序列": bool(valid_values) and all(value == 0 for value in valid_values),
        "短序列": len(valid_values) < config.最小训练样本,
        "有效值数": len(valid_values),
    }


def audit_no_future_samples(
    folds: list[dict[str, Any]],
    points: list[dict[str, Any]],
) -> dict[str, Any]:
    """未来样本检查：确认每个截点的训练样本与误差计算都没有用到未来信息。"""
    checks: list[dict[str, Any]] = []
    for fold in folds:
        if fold["状态"] == "已剔除":
            continue
        passed = (
            fold["训练最大观测期"] is not None
            and fold["训练最大观测期"] <= fold["训练截止期"]
            and (fold["训练最大可用时间"] or "") <= fold["截点可用时间"]
        )
        checks.append({
            "对象": f"折{fold['折序号']}（截止 {fold['训练截止期']}）",
            "检查": "训练样本观测期不晚于训练截止，可见时间不晚于截点",
            "通过": passed,
        })
    for point in points:
        if point["核对状态"] != CHECK_EVALUATED:
            continue
        checks.append({
            "对象": f"折{point['折序号']}/{point['算法']}",
            "检查": "误差仅用目标期实际值，目标期晚于训练截止",
            "通过": point["目标期"] > point["训练截止期"],
        })
    failed = [check for check in checks if not check["通过"]]
    return {
        "通过": not failed,
        "检查项数": len(checks),
        "未通过数": len(failed),
        "检查项": checks,
    }
