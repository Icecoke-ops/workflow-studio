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

from _harness import check, expect_raises, get_registry, invoke, run_cases


def table(plugin, name, config=None, **inputs):
    return invoke(get_registry(), plugin, name, config, **inputs)["table"]


def _abc_frame():
    return pd.DataFrame({"a": [1, 2], "b": [3, 4], "c": [5, 6]})


# ---- SelectColumns ----

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


def case_select_columns_duplicate():
    """重复列名在构造期就报错，不要等到 invoke 才发现。"""
    from engine.schema import fill_defaults

    entry = get_registry().get_component("table", "SelectColumns")
    config = fill_defaults(entry.config_schema, {"columns": ["x", "x"]})
    expect_raises(ValueError, lambda: entry.cls(config), "重复列名", "x")


# ---- CastColumn ----

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


def case_cast_column_numeric_bool():
    data = pd.DataFrame({"flag": [1.0, 0.0, np.nan]})
    result = table(
        "table", "CastColumn", {"column": "flag", "to": "bool"}, data=data
    )
    values = list(result["flag"])
    check(bool(values[0]) is True, f"1.0 应转成 True，实际 {values[0]!r}")
    check(bool(values[1]) is False, f"0.0 应转成 False，实际 {values[1]!r}")
    check(pd.isna(values[2]), f"缺失值应保持 NA，实际 {values[2]!r}")

    ints = pd.DataFrame({"flag": [1, 0]})
    result_int = table(
        "table", "CastColumn", {"column": "flag", "to": "bool"}, data=ints
    )
    check(
        [bool(value) for value in result_int["flag"]] == [True, False],
        f"整数列 1/0 应照旧转换：{result_int['flag'].tolist()}",
    )


def case_cast_column_numeric_bool_invalid():
    data = pd.DataFrame({"flag": [1.0, 2.0]})
    expect_raises(
        ValueError,
        lambda: table(
            "table", "CastColumn", {"column": "flag", "to": "bool"}, data=data
        ),
        "无法转成布尔",
        "2.0",
    )


def case_cast_column_bool_nullable_keeps_na():
    """可空布尔转 bool 要留在 boolean dtype 上，NA 不能被降级成 object。"""
    data = pd.DataFrame({"b": pd.array([True, False, pd.NA], dtype="boolean")})
    result = table("table", "CastColumn", {"column": "b", "to": "bool"}, data=data)
    check(str(result["b"].dtype) == "boolean", f"dtype 应保持 boolean：{result['b'].dtype}")
    check(bool(pd.isna(result["b"].iloc[2])), "NA 应保留")
    check(
        [bool(value) for value in result["b"].iloc[:2]] == [True, False],
        f"布尔值不应被改动：{result['b'].tolist()}",
    )

    plain = pd.DataFrame({"b": [True, False]})
    plain_result = table("table", "CastColumn", {"column": "b", "to": "bool"}, data=plain)
    check(
        [bool(value) for value in plain_result["b"]] == [True, False],
        f"普通 bool 列转换后应保持真假：{plain_result['b'].tolist()}",
    )


# ---- FilterRows：十种 op ----

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


def case_filter_string_column_with_number_error():
    """裸数字被解析成 int；字符串列拿它比较要给出可读错误，
    不能把 pandas 的 "'>' not supported" 原样透出来。"""
    exc = expect_raises(
        ValueError,
        lambda: _filtered("s", "eq", "3"),
        "字符串列",
        "不能与数字",
    )
    text = str(exc)
    check("s" in text, f"错误信息应指出列名：{text!r}")
    check(">" not in text, f"错误信息不应透出 pandas 的 '>' 提示：{text!r}")


def case_filter_string_column_with_quoted_number():
    data = pd.DataFrame({"s": ["3", "abc"]})
    result = table(
        "table",
        "FilterRows",
        {"column": "s", "op": "eq", "value": '"3"'},
        data=data,
    )
    check(
        list(result["s"]) == ["3"],
        f'带引号的 "3" 应按字符串命中：{result["s"].tolist()}',
    )


# ---- FillMissing ----

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


def case_fill_missing_reference_type_errors():
    """data 和 reference 的类型问题要分开报，别把责任推给对象。"""
    data_text = pd.DataFrame({"v": ["x", None]})
    reference_num = pd.DataFrame({"v": [1.0, 2.0]})
    exc = expect_raises(
        ValueError,
        lambda: table(
            "table",
            "FillMissing",
            {"columns": ["v"], "strategy": "mean"},
            data=data_text,
            reference=reference_num,
        ),
        "数据列",
        "不是数值列",
    )
    check("参考表列" not in str(exc), f"应指出是数据列的问题：{exc}")

    data_num = pd.DataFrame({"v": [1.0, np.nan]})
    reference_text = pd.DataFrame({"v": ["x", "y"]})
    exc = expect_raises(
        ValueError,
        lambda: table(
            "table",
            "FillMissing",
            {"columns": ["v"], "strategy": "mean"},
            data=data_num,
            reference=reference_text,
        ),
        "参考表列",
        "不是数值列",
    )
    check("数据列" not in str(exc), f"应指出是参考表列的问题：{exc}")


def _filtered_on(data, column, op, value=None):
    config = {"column": column, "op": op}
    if value is not None:
        config["value"] = value
    return table("table", "FilterRows", config, data=data)


def _datetime_frame():
    return pd.DataFrame({"d": pd.to_datetime(["2024-01-01", "2024-02-01"])})


def case_filter_datetime_in_matches():
    """旧版 datetime 列 op=in 会静默返回 0 行，这条守住能命中。"""
    result = _filtered_on(_datetime_frame(), "d", "in", '["2024-01-01"]')
    check(
        list(result["d"]) == [pd.Timestamp("2024-01-01")],
        f"datetime 列 in 日期串应命中 1 行：{result['d'].tolist()}",
    )


def case_filter_datetime_in_number_rejected():
    expect_raises(
        ValueError,
        lambda: _filtered_on(_datetime_frame(), "d", "in", "[1, 2]"),
        "日期时间列",
        "不能有数字",
    )


def case_filter_datetime_in_empty_array():
    result = _filtered_on(_datetime_frame(), "d", "in", "[]")
    check(len(result) == 0, f"in [] 应返回 0 行且不报错：{len(result)}")


def case_filter_datetime_in_none_does_not_match_nat():
    """[null] 必须在 to_datetime 前过滤掉，否则会生成 NaT 并匹配缺失行。"""
    data = pd.DataFrame({"d": pd.to_datetime(["2024-01-01", None])})
    result = _filtered_on(data, "d", "in", "[null]")
    check(
        len(result) == 0,
        f"in [null] 不应命中任何行（包括 NaT）：{result['d'].tolist()}",
    )


def case_filter_datetime_naive_with_offset_rejected():
    """无时区列拿带偏移的串比较，pandas 会静默全 False；必须提前报错。"""
    expect_raises(
        ValueError,
        lambda: _filtered_on(_datetime_frame(), "d", "eq", "2024-01-01T00:00:00+08:00"),
        "无时区",
        "时区",
    )


def case_filter_datetime_invalid_date_rejected():
    expect_raises(
        ValueError,
        lambda: _filtered_on(_datetime_frame(), "d", "eq", "2024-13-01"),
        "日期值不合法",
        "2024-13-01",
    )


def case_filter_datetime_aware_with_naive_string_matches():
    """带时区列 + 无时区串是 pandas 能命中的一向，只拦会静默返回 False 的反向。"""
    data = pd.DataFrame(
        {"d": pd.to_datetime(["2024-01-01", "2024-02-01"]).tz_localize("Asia/Shanghai")}
    )
    result = _filtered_on(data, "d", "eq", "2024-01-01")
    check(len(result) == 1, f"带时区列与无时区日期串应命中 1 行：{len(result)}")
    check(
        result["d"].iloc[0] == pd.Timestamp("2024-01-01", tz="Asia/Shanghai"),
        f"命中的行不对：{result['d'].tolist()}",
    )


def case_filter_datetime_in_tz_alignment():
    """op=in 的时区口径要与 eq 对齐：带时区列 + naive 串能命中。"""
    aware = pd.DataFrame(
        {"d": pd.to_datetime(["2024-01-01", "2024-02-01"]).tz_localize("Asia/Shanghai")}
    )
    hit = _filtered_on(aware, "d", "in", '["2024-01-01"]')
    check(len(hit) == 1, f"带时区列 in naive 串应命中 1 行：{len(hit)}")
    check(
        hit["d"].iloc[0] == pd.Timestamp("2024-01-01", tz="Asia/Shanghai"),
        f"命中的行不对：{hit['d'].tolist()}",
    )

    expect_raises(
        ValueError,
        lambda: _filtered_on(
            _datetime_frame(), "d", "in", '["2024-01-01T00:00:00+08:00"]'
        ),
        "无时区",
        "时区",
    )
    check(len(_filtered_on(aware, "d", "in", "[]")) == 0, "带时区列 in [] 应返回 0 行")
    check(
        len(_filtered_on(aware, "d", "in", "[null]")) == 0,
        "带时区列 in [null] 应返回 0 行",
    )


def case_fill_missing_no_reference_uses_data():
    """不接 reference：统计量必须取自 data 自己（reference 是可选输入）。"""
    data = pd.DataFrame({"a": [1.0, np.nan, 3.0]})
    result = table(
        "table", "FillMissing", {"columns": ["a"], "strategy": "mean"}, data=data
    )
    check(data["a"].mean() == 2.0, f"数据表自身均值应为 2.0：{data['a'].mean()}")
    check(
        list(result["a"]) == [1.0, 2.0, 3.0],
        f"不接 reference 应填当前表的均值 2.0：{result['a'].tolist()}",
    )


def case_fill_missing_reference_mean():
    data = pd.DataFrame({"a": [1.0, np.nan, 3.0]})  # 自身均值 2.0
    reference = pd.DataFrame({"a": [10.0, 20.0]})  # 参考表均值 15.0
    result = table(
        "table",
        "FillMissing",
        {"columns": ["a"], "strategy": "mean"},
        data=data,
        reference=reference,
    )
    check(
        list(result["a"]) == [1.0, 15.0, 3.0],
        f"应填参考表的均值 15.0，而不是 data 的 2.0：{result['a'].tolist()}",
    )


def case_fill_missing_reference_median():
    data = pd.DataFrame({"a": [1.0, np.nan, 3.0]})  # 自身中位数 2.0
    reference = pd.DataFrame({"a": [10.0, 20.0, 21.0]})  # 参考表中位数 20.0 / 均值 17.0
    result = table(
        "table",
        "FillMissing",
        {"columns": ["a"], "strategy": "median"},
        data=data,
        reference=reference,
    )
    check(
        reference["a"].mean() != 20.0,
        f"参考表均值应与中位数不同，才能证明用的是 median：{reference['a'].mean()}",
    )
    check(
        list(result["a"]) == [1.0, 20.0, 3.0],
        f"应填参考表的中位数 20.0：{result['a'].tolist()}",
    )


def case_fill_missing_reference_mode():
    data = pd.DataFrame({"a": [1.0, 1.0, np.nan]})  # 自身众数 1.0
    reference = pd.DataFrame({"a": [10.0, 10.0, 20.0]})  # 参考表众数 10.0
    result = table(
        "table",
        "FillMissing",
        {"columns": ["a"], "strategy": "mode"},
        data=data,
        reference=reference,
    )
    check(
        list(result["a"]) == [1.0, 1.0, 10.0],
        f"应填参考表的众数 10.0，而不是 data 的 1.0：{result['a'].tolist()}",
    )


def case_fill_missing_reference_missing_column():
    data = pd.DataFrame({"a": [1.0, np.nan]})
    reference = pd.DataFrame({"b": [10.0, 20.0]})
    expect_raises(
        ValueError,
        lambda: table(
            "table",
            "FillMissing",
            {"columns": ["a"], "strategy": "mean"},
            data=data,
            reference=reference,
        ),
        "参考表缺少列",
        "['a']",
        "参考表可用",
        "['b']",
    )


def case_fill_missing_constant_ignores_reference():
    """constant 不需要参考表，参考表缺列也不该报错。"""
    data = pd.DataFrame({"a": [1.0, np.nan]})
    reference = pd.DataFrame({"b": [9.0]})
    result = table(
        "table",
        "FillMissing",
        {"columns": ["a"], "strategy": "constant", "value": "0"},
        data=data,
        reference=reference,
    )
    check(
        list(result["a"]) == [1.0, 0.0],
        f"constant 应照常量填 0.0，不受参考表列影响：{result['a'].tolist()}",
    )


def case_fill_missing_reference_port_optional():
    entry = get_registry().get_component("table", "FillMissing")
    spec = entry.input_schema["reference"]
    check(spec.get("required") is False, f"reference 必须是可选输入：{spec!r}")
    check(
        "std_1.0@table" in spec["types"],
        f"reference 类型必须是 std_1.0@table：{spec.get('types')!r}",
    )


# ---- DropMissing ----

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


# ---- 其余行/列/探查组件 ----

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


def case_rename_columns_collision():
    data = pd.DataFrame({"a": [1], "b": [2]})
    exc = expect_raises(
        ValueError,
        lambda: table("table", "RenameColumns", {"mapping": {"b": "a"}}, data=data),
        "重复",
        "a",
    )
    check("重命名后列名重复" in str(exc), f"错误信息应说明重名：{exc}")

    swapped = table(
        "table", "RenameColumns", {"mapping": {"a": "b", "b": "a"}}, data=data
    )
    check(list(swapped.columns) == ["b", "a"], f"互换列名应合法：{list(swapped.columns)}")


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


def case_value_counts_column_conflict():
    data = pd.DataFrame({"count": [1, 2], "proportion": [0.5, 0.5]})
    exc = expect_raises(
        ValueError,
        lambda: table(
            "table", "ValueCounts", {"column": "count", "normalize": False}, data=data
        ),
        "列名与输出列名冲突",
        "count",
    )
    check("proportion" not in str(exc), f"未开占比时不应提到 proportion：{exc}")

    exc = expect_raises(
        ValueError,
        lambda: table(
            "table",
            "ValueCounts",
            {"column": "proportion", "normalize": True},
            data=data,
        ),
        "列名与输出列名冲突",
        "proportion",
    )
    check("'count'" not in str(exc), f"开占比时不应提到 count 输出列：{exc}")


CASES = [
    ("SelectColumns array 写法与顺序", case_select_columns_array),
    ("SelectColumns strict 缺列报错", case_select_columns_strict_error),
    ("SelectColumns strict 关闭时跳过缺列", case_select_columns_strict_off),
    ("SelectColumns 重复列在构造期报错", case_select_columns_duplicate),
    ('CastColumn to=bool 时 "0" 转 False', case_cast_column_bool_zero),
    ("CastColumn 数值列 1/0 转 bool，缺失保持 NA", case_cast_column_numeric_bool),
    ("CastColumn 数值列出现其他值时报错带真实值", case_cast_column_numeric_bool_invalid),
    ("CastColumn 可空布尔保留 NA 且 dtype=boolean", case_cast_column_bool_nullable_keeps_na),
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
    ("FilterRows 字符串列拿数字比较给出可读错误", case_filter_string_column_with_number_error),
    ("FilterRows 字符串列带引号数字正常命中", case_filter_string_column_with_quoted_number),
    ("FilterRows datetime 列 in 日期串命中", case_filter_datetime_in_matches),
    ("FilterRows datetime 列 in 数字报错", case_filter_datetime_in_number_rejected),
    ("FilterRows datetime 列 in 空数组返回 0 行", case_filter_datetime_in_empty_array),
    ("FilterRows datetime 列 in [null] 不命中 NaT", case_filter_datetime_in_none_does_not_match_nat),
    ("FilterRows 无时区列带偏移串报错", case_filter_datetime_naive_with_offset_rejected),
    ("FilterRows 非法日期串报错", case_filter_datetime_invalid_date_rejected),
    ("FilterRows 带时区列与无时区串命中", case_filter_datetime_aware_with_naive_string_matches),
    ("FilterRows datetime in 与 eq 时区口径一致", case_filter_datetime_in_tz_alignment),
    ("FillMissing mean", case_fill_missing_mean),
    ("FillMissing median", case_fill_missing_median),
    ("FillMissing mode", case_fill_missing_mode),
    ("FillMissing constant", case_fill_missing_constant),
    ("FillMissing 文本列用 mean 报错并指列名", case_fill_missing_mean_text_column),
    ("FillMissing 区分数据列与参考表列的类型错误", case_fill_missing_reference_type_errors),
    ("FillMissing 不接 reference 用当前表统计量", case_fill_missing_no_reference_uses_data),
    ("FillMissing reference mean 取参考表", case_fill_missing_reference_mean),
    ("FillMissing reference median 取参考表", case_fill_missing_reference_median),
    ("FillMissing reference mode 取参考表", case_fill_missing_reference_mode),
    ("FillMissing 参考表缺目标列报错", case_fill_missing_reference_missing_column),
    ("FillMissing constant 不需要参考表", case_fill_missing_constant_ignores_reference),
    ("FillMissing reference 是可选输入", case_fill_missing_reference_port_optional),
    ("DropMissing any / all 语义差异", case_drop_missing_any_vs_all),
    ("ConcatTables 纵向拼接", case_concat_tables),
    ("SortRows 排序", case_sort_rows),
    ("HeadRows 取前 N 行", case_head_rows),
    ("RenameColumns 改名", case_rename_columns),
    ("RenameColumns 改成已有列名报错且互换合法", case_rename_columns_collision),
    ("DropColumns 删列", case_drop_columns),
    ("ValueCounts 值计数", case_value_counts),
    ("ValueCounts 列名与输出列名冲突报错", case_value_counts_column_conflict),
]


def main():
    return run_cases("table", CASES)


if __name__ == "__main__":
    sys.exit(main())
