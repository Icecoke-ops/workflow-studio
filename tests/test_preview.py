"""engine.preview 输出摘要测试（preview 摘要 + detail 详情）。

直接运行：python tests/test_preview.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.preview import DETAIL_MAX_CHARS, MAX_CHARS, detail, preview

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


def case_detail_dataframe():
    import pandas as pd

    rows = 60
    frame = pd.DataFrame(
        {
            "x": list(range(rows)),
            "y": [index * 3 + 100 for index in range(rows)],
        }
    )
    text = detail(frame)
    check(text.startswith("DataFrame shape=(60, 2)"), f"应给出 shape：{text[:60]!r}")
    check("列：x int64，y int64" in text, f"应给出列名与 dtype：{text[:200]!r}")
    check("前 20 行：" in text, f"应给出前 20 行：{text[:200]!r}")
    head = text.split("前 20 行：", 1)[1].split("数值列 describe()：", 1)[0]
    check("\n19" in head, "前 20 行应含索引 19")
    check("\n20" not in head, "前 20 行不应含索引 20")
    check("数值列 describe()：" in text, "数值列应有 describe 段")
    check("count" in text and "mean" in text, "describe 段应含统计量")


def case_detail_series():
    import pandas as pd

    numeric = pd.Series(range(30), name="score")
    text = detail(numeric)
    check(
        "Series name='score' dtype=int64 长度=30" in text,
        f"应给出 name/dtype/长度：{text[:120]!r}",
    )
    check("前 20 个值：" in text, f"应给出前 20 个值：{text[:120]!r}")
    head = text.split("前 20 个值：", 1)[1].split("describe()：", 1)[0]
    check("\n19" in head and "\n20" not in head, "前 20 个值应只到索引 19")
    check("describe()：" in text, "数值 Series 应有 describe 段")

    strings = pd.Series(["值"] * 25, name="s")
    string_text = detail(strings)
    check("长度=25" in string_text, f"字符串 Series 长度：{string_text[:100]!r}")
    check("describe" not in string_text, f"字符串 Series 不应有 describe 段：{string_text[:200]!r}")


def case_detail_ndarray():
    import numpy as np

    array = np.arange(25, dtype="int64").reshape(5, 5)
    text = detail(array)
    check(
        text.startswith("ndarray shape=(5, 5) dtype=int64"),
        f"ndarray 开头不对：{text[:80]!r}",
    )
    check("前 20 个值：" in text, f"应给出前 20 个值：{text[:120]!r}")
    check("24" in text, "前 20 个值应含实际数组内容")


def case_detail_model():
    from engine.api import PredictorModel

    class DemoPredictor(PredictorModel):
        def predict(self, frame):
            return [0.0] * len(frame)

    model = DemoPredictor()
    model.alpha = 0.5
    model.label = "v1"
    model._hidden = 7
    model.frame = object()

    text = detail(model)
    first = text.splitlines()[0]
    check(
        first == f"{DemoPredictor.__name__} ({DemoPredictor.__module__})",
        f"第一行应是类名与模块：{first!r}",
    )
    check("参数：" in text, f"应列出参数：{text!r}")
    check("alpha=0.5" in text, f"标量参数应保留：{text!r}")
    check("label='v1'" in text, f"字符串参数应保留：{text!r}")
    check("hidden" not in text, f"下划线私有项应剔除：{text!r}")
    check("frame=" not in text, f"对象型参数应剔除：{text!r}")


def case_detail_truncate_chars():
    class LongText:
        def __repr__(self):
            return "汉" * 20000

    text = detail(LongText())
    check(
        len(text) == DETAIL_MAX_CHARS,
        f"应截断到 {DETAIL_MAX_CHARS} 个字符，实际 {len(text)}",
    )
    check(
        len(text.encode("utf-8")) > DETAIL_MAX_CHARS,
        "样例应含多字节字符，长度按字符不按字节",
    )
    check("原文 20000 字符" in text, f"尾注应含真实原文长度：{text[-40:]!r}")


def case_detail_never_raises():
    class BadRepr:
        def __repr__(self):
            raise RuntimeError("repr boom")

    class NonStrRepr:
        def __repr__(self):
            return 42

    class BadNameMeta(type):
        @property
        def __name__(cls):
            raise RuntimeError("name boom")

    class BadNameAndRepr(metaclass=BadNameMeta):
        def __repr__(self):
            raise RuntimeError("repr boom")

    cases = [
        ("repr 抛异常", BadRepr()),
        ("repr 返回非 str", NonStrRepr()),
        ("元类 __name__ 与 repr 都抛", BadNameAndRepr()),
    ]
    for label, value in cases:
        text = detail(value)
        check(
            isinstance(text, str) and text != "",
            f"{label} 时 detail() 应返回非空字符串，实际 {text!r}",
        )


CASES = [
    ("DataFrame 摘要", case_dataframe),
    ("Series 摘要", case_series),
    ("ndarray 摘要", case_ndarray),
    ("标量摘要", case_scalar),
    ("None 摘要", case_none),
    ("超长内容截断", case_truncate),
    ("detail DataFrame：shape/列/前 20/describe", case_detail_dataframe),
    ("detail Series：name/dtype/前 20/describe", case_detail_series),
    ("detail ndarray：shape/dtype/前 20", case_detail_ndarray),
    ("detail 模型：类名/模块/标量参数", case_detail_model),
    ("detail 截断：16384 字符且尾注真实原长", case_detail_truncate_chars),
    ("detail 永不抛：坏 repr 与坏元类名", case_detail_never_raises),
]


def main():
    return run_cases("preview", CASES)


if __name__ == "__main__":
    sys.exit(main())
