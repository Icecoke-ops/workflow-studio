"""split 插件组件测试：训练/测试切分与 X / Y 拆分。

直接运行：python tests/test_split.py
"""

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from _harness import (
    check,
    expect_raises,
    get_registry,
    invoke,
    node,
    run_cases,
    run_workflow,
    source_node,
)


# ---- SplitTable ----

def case_split_table_proportion_and_seed():
    data = pd.DataFrame({"v": list(range(100))})
    config = {"test_size": 0.25, "seed": 7, "shuffle": True}
    first = invoke(get_registry(), "split", "SplitTable", config, data=data)
    second = invoke(get_registry(), "split", "SplitTable", config, data=data)
    check(len(first["train"]) == 75, f"train 应是 75 行：{len(first['train'])}")
    check(len(first["test"]) == 25, f"test 应是 25 行：{len(first['test'])}")
    check(
        first["train"].equals(second["train"]) and first["test"].equals(second["test"]),
        "固定 seed 时两次切分应完全一致",
    )


def case_split_table_both_outputs_consumed():
    with tempfile.TemporaryDirectory(prefix="engine_split_test_") as tmp:
        raw = {
            "name": "split",
            "nodes": [
                source_node(tmp),
                node(
                    "n2",
                    "split",
                    "SplitTable",
                    {"test_size": 0.25, "seed": 7, "shuffle": True},
                    {"data": {"from": "n1", "port": "table"}},
                ),
                node(
                    "n3",
                    "table",
                    "HeadRows",
                    {"n": 2},
                    {"data": {"from": "n2", "port": "train"}},
                ),
                node(
                    "n4",
                    "table",
                    "HeadRows",
                    {"n": 1},
                    {"data": {"from": "n2", "port": "test"}},
                ),
            ],
        }
        results = run_workflow(get_registry(), raw)
    check(len(results["n3"].outputs["table"]) == 2, "train 端口应被下游成功消费")
    check(len(results["n4"].outputs["table"]) == 1, "test 端口应被下游成功消费")


def case_split_table_bad_test_size():
    """test_size 边界在构造期就报错，不要等到 invoke 拿到数据才报。"""
    from engine.schema import fill_defaults

    entry = get_registry().get_component("split", "SplitTable")
    for bad in (0, 1):
        config = fill_defaults(entry.config_schema, {"test_size": bad})
        expect_raises(ValueError, lambda c=config: entry.cls(c), "test_size")


# ---- SplitXY ----

def _xy_frame():
    return pd.DataFrame({"x": [1, 2, 3], "z": [4, 5, 6], "y": [7, 8, 9]})


def case_split_xy_columns_and_rows():
    result = invoke(
        get_registry(),
        "split",
        "SplitXY",
        {"feature": ["x", "z"], "target": "y"},
        data=_xy_frame(),
    )
    check(list(result["x"].columns) == ["x", "z"], f"x 列不对：{list(result['x'].columns)}")
    check(list(result["y"].columns) == ["y"], f"y 列不对：{list(result['y'].columns)}")
    check(len(result["x"]) == 3, f"x 行数不对：{len(result['x'])}")
    check(len(result["y"]) == 3, f"y 行数不对：{len(result['y'])}")


def case_split_xy_rows_correspond():
    data = _xy_frame()
    result = invoke(
        get_registry(),
        "split",
        "SplitXY",
        {"feature": ["x"], "target": "y"},
        data=data,
    )
    check(list(result["x"]["x"]) == list(data["x"]), "x 与输入首列应逐行对应")
    check(list(result["y"]["y"]) == list(data["y"]), "y 与输入目标列应逐行对应")
    check(
        list(result["x"].index) == list(result["y"].index),
        "x / y 的行索引应一一对应",
    )


def case_split_xy_missing_column():
    expect_raises(
        ValueError,
        lambda: invoke(
            get_registry(),
            "split",
            "SplitXY",
            {"feature": ["nope"], "target": "y"},
            data=_xy_frame(),
        ),
        "列不存在",
        "nope",
        "可用",
        "x",
    )


def case_split_xy_target_in_feature():
    expect_raises(
        ValueError,
        lambda: invoke(
            get_registry(),
            "split",
            "SplitXY",
            {"feature": ["x", "y"], "target": "y"},
            data=_xy_frame(),
        ),
        "目标列 y",
        "不能同时出现在特征列里",
    )


def case_split_xy_duplicate_feature():
    exc = expect_raises(
        ValueError,
        lambda: invoke(
            get_registry(),
            "split",
            "SplitXY",
            {"feature": ["x", "x"], "target": "y"},
            data=_xy_frame(),
        ),
        "重复",
        "x",
    )
    check("feature 里有重复列名" in str(exc), f"错误信息应说明 feature 重复：{exc}")

    result = invoke(
        get_registry(),
        "split",
        "SplitXY",
        {"feature": ["x"], "target": "y"},
        data=_xy_frame(),
    )
    check(list(result["x"].columns) == ["x"], f"正常拆列不受影响：{list(result['x'].columns)}")


CASES = [
    ("SplitTable 比例正确且 seed 可复现", case_split_table_proportion_and_seed),
    ("SplitTable test_size 边界在构造期报错", case_split_table_bad_test_size),
    ("SplitTable 两个输出端口都被下游消费", case_split_table_both_outputs_consumed),
    ("SplitXY 输出列名与行数正确", case_split_xy_columns_and_rows),
    ("SplitXY x / y 行对行一一对应", case_split_xy_rows_correspond),
    ("SplitXY 缺列报错并给出可用列名", case_split_xy_missing_column),
    ("SplitXY 目标列出现在特征列里报错", case_split_xy_target_in_feature),
    ("SplitXY feature 重复列名报错", case_split_xy_duplicate_feature),
]


def main():
    return run_cases("split", CASES)


if __name__ == "__main__":
    sys.exit(main())
