"""fileio 插件组件测试：CSV / Excel 读写与路径里的 ${变量} 展开。

直接运行：python tests/test_fileio.py
"""

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.errors import ExecutionError

from _harness import (
    check,
    env_guard,
    expect_raises,
    get_registry,
    invoke,
    node,
    run_cases,
    run_workflow,
    source_node,
)


def table(plugin, name, config=None, **inputs):
    return invoke(get_registry(), plugin, name, config, **inputs)["table"]


# ---- LoadCSV ----

def case_load_csv_plain():
    with tempfile.TemporaryDirectory(prefix="engine_fileio_test_") as tmp:
        path = Path(tmp) / "data.csv"
        path.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
        result = table("fileio", "LoadCSV", {"path": str(path)})
    check(list(result.columns) == ["x", "y"], f"列名不对：{list(result.columns)}")
    check(list(result["x"]) == [1, 3], f"数据不对：{result['x'].tolist()}")


def case_load_csv_sep():
    with tempfile.TemporaryDirectory(prefix="engine_fileio_test_") as tmp:
        path = Path(tmp) / "data.txt"
        path.write_text("x;y\n1;2\n", encoding="utf-8")
        result = table("fileio", "LoadCSV", {"path": str(path), "sep": ";"})
    check(list(result.columns) == ["x", "y"], f"分号分隔没生效：{list(result.columns)}")


def case_load_csv_no_header():
    with tempfile.TemporaryDirectory(prefix="engine_fileio_test_") as tmp:
        path = Path(tmp) / "data.csv"
        path.write_text("1,2\n3,4\n", encoding="utf-8")
        result = table("fileio", "LoadCSV", {"path": str(path), "header": False})
    check(
        list(result.columns) == [0, 1],
        f"header=False 时列名应是 0、1：{list(result.columns)}",
    )
    check(len(result) == 2, f"应读到 2 行：{len(result)}")


def case_load_csv_gbk():
    with tempfile.TemporaryDirectory(prefix="engine_fileio_test_") as tmp:
        path = Path(tmp) / "data.csv"
        path.write_bytes("名称,值\n甲,1\n".encode("gbk"))
        result = table("fileio", "LoadCSV", {"path": str(path), "encoding": "gbk"})
    check(list(result.columns) == ["名称", "值"], f"中文列名不对：{list(result.columns)}")
    check(result["名称"].iloc[0] == "甲", f"中文内容不对：{result['名称'].tolist()}")


# ---- LoadExcel ----

def _write_workbook(path):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({"a": [1, 2]}).to_excel(writer, sheet_name="First", index=False)
        pd.DataFrame({"b": [3, 4]}).to_excel(writer, sheet_name="Second", index=False)


def case_load_excel_default_sheet():
    with tempfile.TemporaryDirectory(prefix="engine_fileio_test_") as tmp:
        path = Path(tmp) / "book.xlsx"
        _write_workbook(path)
        result = table("fileio", "LoadExcel", {"path": str(path)})
    check(list(result.columns) == ["a"], f"默认应读第一个 sheet：{list(result.columns)}")


def case_load_excel_named_sheet():
    with tempfile.TemporaryDirectory(prefix="engine_fileio_test_") as tmp:
        path = Path(tmp) / "book.xlsx"
        _write_workbook(path)
        result = table("fileio", "LoadExcel", {"path": str(path), "sheet": "Second"})
    check(list(result.columns) == ["b"], f"指定 sheet 没生效：{list(result.columns)}")


# ---- SaveCSV ----

def case_save_csv_empty_output():
    """SaveCSV 输出端口为空，执行器必须接受 {}；回读内容要与写入一致。"""
    with tempfile.TemporaryDirectory(prefix="engine_fileio_test_") as tmp:
        written = Path(tmp) / "out.csv"
        raw = {
            "name": "save",
            "nodes": [
                source_node(tmp),
                node(
                    "n2",
                    "fileio",
                    "SaveCSV",
                    {"path": str(written)},
                    {"data": {"from": "n1", "port": "table"}},
                ),
            ],
        }
        results = run_workflow(get_registry(), raw)
        check(results["n2"].outputs == {}, f"空输出应为 {{}}：{results['n2'].outputs}")
        check(written.is_file(), f"应写出 {written}")
        original = results["n1"].outputs["table"]
        back = table("fileio", "LoadCSV", {"path": str(written)})
    check(list(back.columns) == list(original.columns), "回读列名应与写入一致")
    check(
        np.allclose(back.to_numpy(dtype=float), original.to_numpy(dtype=float)),
        "回读数据应与写入一致",
    )


# ---- 路径里的 ${变量} ----

def case_workspace_expanded():
    with tempfile.TemporaryDirectory(prefix="engine_fileio_test_") as tmp, env_guard():
        (Path(tmp) / "data.csv").write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
        os.environ["workspace"] = tmp
        raw = {
            "name": "csv",
            "nodes": [
                node(
                    "n1",
                    "fileio",
                    "LoadCSV",
                    {"path": "${workspace}/data.csv"},
                )
            ],
        }
        results = run_workflow(get_registry(), raw)
        result = results["n1"].outputs["table"]
    check(list(result.columns) == ["x", "y"], f"列名不对：{list(result.columns)}")
    check(list(result["x"]) == [1, 3], f"数据不对：{list(result['x'])}")


def case_undefined_env_fails():
    with env_guard():
        os.environ.pop("ENGINE_CSV_NOPE", None)
        raw = {
            "name": "csv",
            "nodes": [
                node(
                    "n1",
                    "fileio",
                    "LoadCSV",
                    {"path": "${ENGINE_CSV_NOPE}/data.csv"},
                )
            ],
        }
        expect_raises(
            ExecutionError,
            lambda: run_workflow(get_registry(), raw),
            "初始化失败",
            "n1",
            "环境变量未定义",
            "ENGINE_CSV_NOPE",
        )


CASES = [
    ("LoadCSV 正常读取", case_load_csv_plain),
    ("LoadCSV 自定义分隔符", case_load_csv_sep),
    ("LoadCSV header=False", case_load_csv_no_header),
    ("LoadCSV GBK 编码", case_load_csv_gbk),
    ("LoadExcel 默认读第一个 sheet", case_load_excel_default_sheet),
    ("LoadExcel 指定 sheet", case_load_excel_named_sheet),
    ("SaveCSV 空输出被接受且回读一致", case_save_csv_empty_output),
    ("${workspace} 展开后能读到 CSV", case_workspace_expanded),
    ("未定义变量导致执行失败且提示变量名", case_undefined_env_fails),
]


def main():
    return run_cases("fileio", CASES)


if __name__ == "__main__":
    sys.exit(main())
