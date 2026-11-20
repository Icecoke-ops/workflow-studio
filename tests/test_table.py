"""table 插件组件行为测试：直接调组件，config 按引擎规则补默认值。

直接运行：python tests/test_table.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.registry import Registry

from _harness import check, expect_raises, invoke, run_cases


_REGISTRY = None


def get_registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = Registry().load(ROOT / "plugins")
    return _REGISTRY


def table(plugin, name, config=None, **inputs):
    return invoke(get_registry(), plugin, name, config, **inputs)["table"]


def _abc_frame():
    return pd.DataFrame({"a": [1, 2], "b": [3, 4], "c": [5, 6]})


# --------------------------------------------------------------------------
# SelectColumns
# --------------------------------------------------------------------------

def case_select_columns_array():
    result = table(
        "table", "SelectColumns", {"columns": ["c", "a"]}, data=_abc_frame()
    )
    check(list(result.columns) == ["c", "a"], f"选列与顺序不对：{list(result.columns)}")


def case_select_columns_strict_error():
    expect_raises(
        ValueError,
        lambda: table(
            "table", "SelectColumns", {"columns": ["a", "nope"]}, data=_abc_frame()
        ),
        "列不存在",
        "nope",
    )


def case_select_columns_strict_off():
    result = table(
        "table",
        "SelectColumns",
        {"columns": ["a", "nope"], "strict": False},
        data=_abc_frame(),
    )
    check(list(result.columns) == ["a"], f"缺列应被跳过：{list(result.columns)}")


# --------------------------------------------------------------------------
# CastColumn
# --------------------------------------------------------------------------

def case_cast_column_bool_zero():
    """astype(bool) 会把 "0" 当成 True，这里守住按字面量转换。"""
    data = pd.DataFrame({"flag": ["0", "1", "true", "false"]})
    result = table(
        "table", "CastColumn", {"column": "flag", "to": "bool"}, data=data
    )
    values = [bool(value) for value in result["flag"]]
    check(
        values == [False, True, True, False],
        f'字符串 "0" 必须转成 False，实际 {values}',
    )


# --------------------------------------------------------------------------
# FilterRows：十种 op
# --------------------------------------------------------------------------

def _filter_frame():
    return pd.DataFrame({"n": [1.0, 2.0, 3.0, np.nan], "s": ["abc", "bcd", "xyz", np.nan]})


def _filtered(column, op, value=None):
    config = {"column": column, "op": op}
    if value is not None:
        config["value"] = value
    return table("table", "FilterRows", config, data=_filter_frame())


def case_filter_eq():
    result = _filtered("n", "eq", "3")
    check(list(result["n"]) == [3.0], f"eq 结果不对：{result['n'].tolist()}")


def case_filter_ne():
    result = _filtered("n", "ne", "3")
    check(len(result) == 3, f"ne 应保留 3 行（含缺失），实际 {len(result)}")


def case_filter_gt():
    result = _filtered("n", "gt", "1")
    check(list(result["n"]) == [2.0, 3.0], f"gt 结果不对：{result['n'].tolist()}")


def case_filter_ge():
    result = _filtered("n", "ge", "2")
    check(list(result["n"]) == [2.0, 3.0], f"ge 结果不对：{result['n'].tolist()}")


def case_filter_lt():
    result = _filtered("n", "lt", "2")
    check(list(result["n"]) == [1.0], f"lt 结果不对：{result['n'].tolist()}")


def case_filter_le():
    result = _filtered("n", "le", "2")
    check(list(result["n"]) == [1.0, 2.0], f"le 结果不对：{result['n'].tolist()}")


def case_filter_in():
    result = _filtered("n", "in", "[1,3]")
    check(list(result["n"]) == [1.0, 3.0], f"in 结果不对：{result['n'].tolist()}")


def case_filter_contains():
    result = _filtered("s", "contains", "abc")
    check(list(result["s"]) == ["abc"], f"contains 结果不对：{result['s'].tolist()}")


def case_filter_notnull():
    result = _filtered("s", "notnull")
    check(len(result) == 3, f"notnull 应保留 3 行：{len(result)}")


def case_filter_isnull():
    result = _filtered("s", "isnull")
    check(len(result) == 1, f"isnull 应保留 1 行：{len(result)}")


# --------------------------------------------------------------------------
# FillMissing
# --------------------------------------------------------------------------

def _missing_num_frame():
    return pd.DataFrame({"v": [1.0, np.nan, 3.0]})


def case_fill_missing_mean():
    result = table(
        "table",
        "FillMissing",
        {"columns": ["v"], "strategy": "mean"},
        data=_missing_num_frame(),
    )
    check(list(result["v"]) == [1.0, 2.0, 3.0], f"mean 填充不对：{result['v'].tolist()}")


def case_fill_missing_median():
    result = table(
        "table",
        "FillMissing",
        {"columns": ["v"], "strategy": "median"},
        data=_missing_num_frame(),
    )
    check(list(result["v"]) == [1.0, 2.0, 3.0], f"median 填充不对：{result['v'].tolist()}")


def case_fill_missing_mode():
    data = pd.DataFrame({"s": ["a", np.nan, "a", "b"]})
    result = table(
        "table", "FillMissing", {"columns": ["s"], "strategy": "mode"}, data=data
    )
    check(list(result["s"]) == ["a", "a", "a", "b"], f"mode 填充不对：{result['s'].tolist()}")


def case_fill_missing_constant():
    result = table(
        "table",
        "FillMissing",
        {"columns": ["v"], "strategy": "constant", "value": "0"},
        data=_missing_num_frame(),
    )
    check(list(result["v"]) == [1.0, 0.0, 3.0], f"常量填充不对：{result['v'].tolist()}")


def case_fill_missing_mean_text_column():
    data = pd.DataFrame({"s": ["a", np.nan]})
    expect_raises(
        ValueError,
        lambda: table(
            "table",
            "FillMissing",
            {"columns": ["s"], "strategy": "mean"},
            data=data,
        ),
        "列 s",
        "不是数值列",
    )


# --------------------------------------------------------------------------
# DropMissing
# --------------------------------------------------------------------------

def case_drop_missing_any_vs_all():
    data = pd.DataFrame(
        {"a": [1.0, np.nan, 3.0, np.nan], "b": [np.nan, 2.0, 4.0, np.nan]}
    )
    any_out = table("table", "DropMissing", {"how": "any"}, data=data)
    all_out = table("table", "DropMissing", {"how": "all"}, data=data)
    check(len(any_out) == 1, f"how=any 应只留完整行 1 行：{len(any_out)}")
    check(list(any_out["a"]) == [3.0], f"how=any 留下的行不对：{any_out['a'].tolist()}")
    check(len(all_out) == 3, f"how=all 只删全缺行，应留 3 行：{len(all_out)}")
    check(all_out.notna().any().all(), "how=all 不应删掉部分缺失的行")


# --------------------------------------------------------------------------
# 其余行/列/探查组件
# --------------------------------------------------------------------------

def case_concat_tables():
    first = pd.DataFrame({"a": [1, 2]})
    second = pd.DataFrame({"a": [3, 4]})
    result = table(
        "table", "ConcatTables", {"ignore_index": True}, first=first, second=second
    )
    check(list(result["a"]) == [1, 2, 3, 4], f"拼接结果不对：{result['a'].tolist()}")
    check(list(result.index) == [0, 1, 2, 3], f"ignore_index 没生效：{list(result.index)}")


def case_sort_rows():
    data = pd.DataFrame({"x": [3, 1, 2]})
    result = table("table", "SortRows", {"by": ["x"]}, data=data)
    check(list(result["x"]) == [1, 2, 3], f"排序结果不对：{result['x'].tolist()}")


def case_head_rows():
    data = pd.DataFrame({"v": [1, 2, 3, 4]})
    result = table("table", "HeadRows", {"n": 2}, data=data)
    check(list(result["v"]) == [1, 2], f"取前 N 行不对：{result['v'].tolist()}")


def case_rename_columns():
    data = pd.DataFrame({"a": [1], "b": [2]})
    result = table("table", "RenameColumns", {"mapping": {"a": "A"}}, data=data)
    check(list(result.columns) == ["A", "b"], f"改名结果不对：{list(result.columns)}")


def case_drop_columns():
    data = pd.DataFrame({"a": [1], "b": [2]})
    result = table("table", "DropColumns", {"columns": ["b"]}, data=data)
    check(list(result.columns) == ["a"], f"删列结果不对：{list(result.columns)}")


def case_value_counts():
    data = pd.DataFrame({"c": ["a", "b", "a", "a"]})
    result = table("table", "ValueCounts", {"column": "c"}, data=data)
    check(list(result.columns) == ["c", "count"], f"计数表列名不对：{list(result.columns)}")
    counts = dict(zip(result["c"], result["count"]))
    check(counts == {"a": 3, "b": 1}, f"计数结果不对：{counts}")


CASES = [
    ("SelectColumns array 写法与顺序", case_select_columns_array),
    ("SelectColumns strict 缺列报错", case_select_columns_strict_error),
    ("SelectColumns strict 关闭时跳过缺列", case_select_columns_strict_off),
    ('CastColumn to=bool 时 "0" 转 False', case_cast_column_bool_zero),
    ("FilterRows eq", case_filter_eq),
    ("FilterRows ne", case_filter_ne),
    ("FilterRows gt", case_filter_gt),
    ("FilterRows ge", case_filter_ge),
    ("FilterRows lt", case_filter_lt),
    ("FilterRows le", case_filter_le),
    ("FilterRows in", case_filter_in),
    ("FilterRows contains", case_filter_contains),
    ("FilterRows notnull", case_filter_notnull),
    ("FilterRows isnull", case_filter_isnull),
    ("FillMissing mean", case_fill_missing_mean),
    ("FillMissing median", case_fill_missing_median),
    ("FillMissing mode", case_fill_missing_mode),
    ("FillMissing constant", case_fill_missing_constant),
    ("FillMissing 文本列用 mean 报错并指列名", case_fill_missing_mean_text_column),
    ("DropMissing any / all 语义差异", case_drop_missing_any_vs_all),
    ("ConcatTables 纵向拼接", case_concat_tables),
    ("SortRows 排序", case_sort_rows),
    ("HeadRows 取前 N 行", case_head_rows),
    ("RenameColumns 改名", case_rename_columns),
    ("DropColumns 删列", case_drop_columns),
    ("ValueCounts 值计数", case_value_counts),
]


def main():
    return run_cases("table", CASES)


if __name__ == "__main__":
    sys.exit(main())
