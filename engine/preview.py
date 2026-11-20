"""运行结果的文本摘要，CLI 和 Web 共用。"""

MAX_CHARS = 600


def _cut(text, limit):
    return text if len(text) <= limit else text[:limit] + "…"


def preview(value):
    try:
        import pandas as pd
    except Exception:  # 没装 pandas 也要能跑
        pd = None

    if pd is not None:
        if isinstance(value, pd.DataFrame):
            columns = [str(c) for c in value.columns]
            head = value.head(5).to_string()
            return _cut(
                f"DataFrame {value.shape[0]} 行 × {value.shape[1]} 列 {columns}\n{head}",
                MAX_CHARS,
            )
        if isinstance(value, pd.Series):
            return _cut(f"Series {len(value)} 项\n{value.head(5).to_string()}", MAX_CHARS)

    if type(value).__name__ == "ndarray":
        shape = getattr(value, "shape", "?")
        return _cut(f"ndarray shape={shape}\n{value!r}", MAX_CHARS)

    if isinstance(value, (str, int, float, bool)) or value is None:
        return _cut(repr(value), MAX_CHARS)

    return _cut(f"{type(value).__name__} {value!r}", MAX_CHARS)
