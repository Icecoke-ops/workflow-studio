"""engine.preview 输出摘要测试（DataFrame / Series / ndarray / 标量 / None）。

直接运行：python tests/test_preview.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.preview import MAX_CHARS, preview

from _harness import check, run_cases


def case_dataframe():
    import pandas as pd

    frame = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    text = preview(frame)
    check(
        text.startswith("DataFrame 3 行 × 2 列"),
        f"DataFrame 摘要开头不对：{text!r}",
    )
    check("['a', 'b']" in text, f"应列出列名：{text!r}")


def case_series():
    import pandas as pd

    text = preview(pd.Series([1, 2, 3]))
    check(text.startswith("Series 3 项"), f"Series 摘要开头不对：{text!r}")


def case_ndarray():
    import numpy as np

    text = preview(np.arange(4))
    check(text.startswith("ndarray shape=(4,)"), f"ndarray 摘要开头不对：{text!r}")


def case_scalar():
    check(preview(3.5) == "3.5", f"float 标量：{preview(3.5)!r}")
    check(preview(0) == "0", f"int 标量：{preview(0)!r}")
    check(preview(True) == "True", f"bool 标量：{preview(True)!r}")
    check(preview("abc") == "'abc'", f"str 标量：{preview('abc')!r}")


def case_none():
    check(preview(None) == "None", f"None：{preview(None)!r}")


def case_truncate():
    text = preview("a" * (MAX_CHARS + 50))
    check(len(text) == MAX_CHARS + 1, f"超长内容应截断到 {MAX_CHARS} + 省略号，实际长度 {len(text)}")
    check(text.endswith("…"), f"截断后应以省略号结尾：{text[-5:]!r}")


CASES = [
    ("DataFrame 摘要", case_dataframe),
    ("Series 摘要", case_series),
    ("ndarray 摘要", case_ndarray),
    ("标量摘要", case_scalar),
    ("None 摘要", case_none),
    ("超长内容截断", case_truncate),
]


def main():
    return run_cases("preview", CASES)


if __name__ == "__main__":
    sys.exit(main())
