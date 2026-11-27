"""core 独立运行契约：引擎不依赖后端，第三方插件从零可跑。

直接运行：python tests/test_standalone.py
"""

import io
import sys
import tempfile
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.registry import Registry
from engine.runner import run
from engine.workflow import validate

from _harness import check, plugin_source, run_cases, write_plugin


def case_missing_dir_only_std():
    with redirect_stderr(io.StringIO()) as captured:
        registry = Registry().load(ROOT / "no_such_plugins_dir")
    check(
        sorted(registry.plugins) == ["std"],
        f"目录不存在时只应有 std：{sorted(registry.plugins)}",
    )
    check(
        "插件目录不存在" in captured.getvalue(),
        f"应输出目录警告：{captured.getvalue()!r}",
    )


def case_engine_has_no_backend_dependency():
    files = sorted((ROOT / "engine").glob("*.py"))
    check(files, "engine/ 下没有找到 .py 文件")
    for path in files:
        text = path.read_text(encoding="utf-8")
        for word in ("studio", "frontend"):
            check(
                word not in text,
                f"{path.name} 不应出现 {word!r}（引擎不能反向依赖后端）",
            )


def case_third_party_plugin_runs():
    with tempfile.TemporaryDirectory(prefix="engine_standalone_test_") as tmp:
        source = plugin_source(
            "solo",
            class_name="Answer",
            output_schema='{"result": {"type": "std_1.0@number"}}',
            invoke_body='return {"result": 42}',
        )
        write_plugin(
            tmp,
            "solo",
            {"__init__.py": "", "components.py": source},
        )
        registry = Registry().load(tmp)
        check(
            registry.get_component("solo", "Answer") is not None,
            "第三方插件应加载成功",
        )
        check(
            sorted(registry.plugins) == ["solo", "std"],
            f"不应依赖 core/fileio/ml/split/table：{sorted(registry.plugins)}",
        )

        raw = {
            "name": "solo",
            "nodes": [
                {
                    "id": "n1",
                    "plugin": "solo",
                    "component": "Answer",
                    "config": {},
                    "inputs": {},
                }
            ],
        }
        report = validate(registry, raw)
        check(report.ok, f"单节点工作流应校验通过：{report.errors}")
        results = run(report.workflow, registry)
        check(
            results["n1"].outputs == {"result": 42},
            f"运行结果不对：{results['n1'].outputs}",
        )


CASES = [
    ("目录不存在时只加载 std", case_missing_dir_only_std),
    ("engine 不出现 studio/frontend 字样", case_engine_has_no_backend_dependency),
    ("第三方插件从零加载并运行", case_third_party_plugin_runs),
]


def main():
    return run_cases("standalone", CASES)


if __name__ == "__main__":
    sys.exit(main())
