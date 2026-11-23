"""运行结果的文本摘要，CLI 和 Web 共用。"""

from .api import PredictorModel

MAX_CHARS = 600
DETAIL_MAX_CHARS = 16 * 1024


def _cut(text, limit=MAX_CHARS):
    return text if len(text) <= limit else text[:limit] + "…"


def preview(value):
    pd = _pandas()

    if pd is not None:
        if isinstance(value, pd.DataFrame):
            columns = [str(c) for c in value.columns]
            head = value.head(5).to_string()
            return _cut(f"DataFrame {value.shape[0]} 行 × {value.shape[1]} 列 {columns}\n{head}")
        if isinstance(value, pd.Series):
            return _cut(f"Series {len(value)} 项\n{value.head(5).to_string()}")

    if type(value).__name__ == "ndarray":
        shape = getattr(value, "shape", "?")
        return _cut(f"ndarray shape={shape}\n{value!r}")

    if isinstance(value, (str, int, float, bool)) or value is None:
        return _cut(repr(value))

    return _cut(f"{type(value).__name__} {value!r}")


def detail(value) -> str:
    """单个端口的详细文本，给「点开看详情」用；任何值都不抛异常。"""
    try:
        text = _detail_text(value)
    except Exception:
        text = _safe_repr(value)
    try:
        return _truncate_detail(text)
    except Exception:
        return "<无法显示>"


def _safe_repr(value, limit=None):
    try:
        text = repr(value)
    except Exception:
        return "<无法显示>"
    return text if limit is None else _cut(text, limit)


def _truncate_detail(text):
    if len(text) <= DETAIL_MAX_CHARS:
        return text
    suffix = f"…（已截断，原文 {len(text)} 字符）"
    return text[: DETAIL_MAX_CHARS - len(suffix)] + suffix


def _pandas():
    try:
        import pandas as pd
    except Exception:  # 没装 pandas 也要能跑
        return None
    return pd


def _detail_text(value):
    pd = _pandas()
    if pd is not None:
        if isinstance(value, pd.DataFrame):
            return _frame_detail(value)
        if isinstance(value, pd.Series):
            return _series_detail(value, pd)

    if isinstance(value, PredictorModel):
        return _model_detail(value)
    if type(value).__name__ == "ndarray":
        return _array_detail(value)
    if isinstance(value, str):
        return f"str 长度={len(value)}\n{value[:500]}{'…' if len(value) > 500 else ''}"
    if value is None or isinstance(value, (bool, int, float)):
        return repr(value)
    if isinstance(value, dict):
        return _mapping_detail(value)
    if isinstance(value, (list, tuple)):
        return _sequence_detail(value)
    return _safe_repr(value)


def _frame_detail(value):
    dtypes = "，".join(f"{name} {dtype}" for name, dtype in value.dtypes.items())
    lines = [
        f"DataFrame shape={tuple(value.shape)}",
        f"列：{dtypes}",
        "前 20 行：",
        value.head(20).to_string(),
    ]
    numeric = value.select_dtypes(include="number")
    if numeric.shape[1]:
        lines += ["数值列 describe()：", numeric.describe().to_string()]
    return "\n".join(lines)


def _series_detail(value, pd):
    lines = [
        f"Series name={_safe_repr(value.name, 100)} dtype={value.dtype} 长度={len(value)}",
        "前 20 个值：",
        value.head(20).to_string(),
    ]
    if pd.api.types.is_numeric_dtype(value):
        lines += ["describe()：", value.describe().to_string()]
    return "\n".join(lines)


def _array_detail(value):
    try:
        head = value[:20]
    except Exception:
        head = value
    shape = getattr(value, "shape", "?")
    dtype = getattr(value, "dtype", "?")
    return f"ndarray shape={shape} dtype={dtype}\n前 20 个值：\n{_safe_repr(head)}"


def _model_detail(value):
    cls = type(value)
    lines = [f"{cls.__name__} ({cls.__module__})"]

    raw = None
    getter = getattr(value, "get_params", None)
    if callable(getter):
        try:
            raw = getter()
        except Exception:
            raw = None
    if not isinstance(raw, dict) or not raw:
        try:
            raw = vars(value)
        except Exception:
            raw = None

    params = []
    if isinstance(raw, dict):
        for key, param in list(raw.items())[:20]:
            if key.startswith("_") or not isinstance(param, (str, int, float, bool, type(None))):
                continue
            params.append(f"{key}={_safe_repr(param, 120)}")
    if params:
        lines.append("参数：" + "，".join(params))
    return "\n".join(lines)


def _mapping_detail(value):
    lines = [f"dict {len(value)} 项"]
    for key, item in list(value.items())[:10]:
        lines.append(f"{_safe_repr(key, 100)}: {_safe_repr(item, 200)}")
    if len(value) > 10:
        lines.append(f"…其余 {len(value) - 10} 项未显示")
    return "\n".join(lines)


def _sequence_detail(value):
    lines = [f"{type(value).__name__} {len(value)} 项"]
    for index, item in enumerate(value[:10]):
        lines.append(f"{index}: {_safe_repr(item, 200)}")
    if len(value) > 10:
        lines.append(f"…其余 {len(value) - 10} 项未显示")
    return "\n".join(lines)
