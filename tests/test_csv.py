"""core.LoadCSV 的 ``${VAR}`` 路径展开测试。

直接运行：python tests/test_csv.py
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.errors import ExecutionError
from engine.registry import Registry
from engine.runner import run
from engine.workflow import validate

from _harness import check, env_guard, expect_raises, run_cases


_REGISTRY = None


def get_registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = Registry().load(ROOT / "plugins")
    return _REGISTRY


def _load_csv_workflow(path):
    return {
        "name": "csv",
        "nodes": [
            {
                "id": "n1",
                "plugin": "core",
                "component": "LoadCSV",
                "config": {"path": path},
                "inputs": {},
            }
        ],
    }


def case_workspace_expanded():
    with env_guard(), tempfile.TemporaryDirectory(prefix="engine_csv_test_") as tmp:
        data = Path(tmp) / "data.csv"
        data.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
        os.environ["workspace"] = tmp

        registry = get_registry()
        report = validate(registry, _load_csv_workflow("${workspace}/data.csv"))
        check(report.ok, f"工作流应校验通过，实际错误：{report.errors}")
        results = run(report.workflow, registry)
        table = results["n1"].outputs["table"]

    check(list(table.columns) == ["x", "y"], f"列名不对：{list(table.columns)}")
    check(
        list(table["x"]) == [1, 3] and list(table["y"]) == [2, 4],
        f"数据不对：x={list(table['x'])} y={list(table['y'])}",
    )


def case_undefined_env_fails():
    with env_guard():
        os.environ.pop("ENGINE_CSV_NOPE", None)
        registry = get_registry()
        report = validate(registry, _load_csv_workflow("${ENGINE_CSV_NOPE}/data.csv"))
        check(report.ok, f"工作流应校验通过（路径只是字符串），实际错误：{report.errors}")

        expect_raises(
            ExecutionError,
            lambda: run(report.workflow, registry),
            "初始化失败",
            "n1",
            "环境变量未定义",
            "ENGINE_CSV_NOPE",
        )


CASES = [
    ("${workspace} 展开后能读到 CSV", case_workspace_expanded),
    ("未定义变量导致执行失败且提示变量名", case_undefined_env_fails),
]


def main():
    return run_cases("csv", CASES)


if __name__ == "__main__":
    sys.exit(main())
