"""一条命令跑完全链路：打包插件 -> 加载 -> 校验 -> 执行 -> 断言。

    python tests/smoke.py

插件 zip 和输出文件都落在系统临时目录，跑完清理，不往仓库里丢东西。
示例工作流里的 ``${workspace}`` 在这里指向临时目录，所以 SaveCSV 不会写到仓库根。
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.api import PredictorModel  # noqa: E402
from engine.registry import Registry  # noqa: E402
from engine.runner import run  # noqa: E402
from engine.workflow import validate  # noqa: E402
from tools.build_plugins import build_all  # noqa: E402

WORKFLOW = ROOT / "workflows" / "regression_demo.json"


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[OK] {message}")


def expect_error(registry, payload, keyword, label):
    report = validate(registry, payload)
    check(not report.ok, f"{label}：应被拒绝")
    joined = " | ".join(report.errors)
    check(keyword in joined, f"{label}：错误信息含 {keyword!r}")
    print(f"     -> {joined}")


def write_data(directory, rows=200, seed=42):
    """示例工作流从 ${workspace}/data.csv 读数据，这里现造一份，用完随临时目录删掉。"""
    import random

    rng = random.Random(seed)
    lines = ["x,y"]
    for _ in range(rows):
        x = rng.uniform(0, 10)
        lines.append(f"{x:.6f},{2 * x + 1 + 0.5 * rng.gauss(0, 1):.6f}")
    (directory / "data.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    temp = Path(tempfile.mkdtemp(prefix="wf_smoke_"))
    saved_workspace = os.environ.get("workspace")
    try:
        plugin_dir = temp / "plugins"
        out_dir = temp / "out"
        out_dir.mkdir()
        os.environ["workspace"] = str(out_dir)

        built = build_all(plugin_dir)
        check(len(built) == 5, f"打包出 {len(built)} 个插件")

        registry = Registry().load(plugin_dir)
        check(
            sorted(registry.plugins) == ["core", "fileio", "ml", "split", "std", "table"],
            f"插件集合 {sorted(registry.plugins)}",
        )
        check(len(registry.components) == 25, f"组件数 {len(registry.components)}")
        check("std_1.0@model" in registry.types, "标准模型类型已注册")
        check("std_1.0@table" in registry.types, "标准表格类型已注册")
        check("std_1.0@model" in registry.models, "标准模型类型已绑定 PredictorModel")

        write_data(out_dir)

        raw = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        report = validate(registry, raw)
        if not report.ok:
            for error in report.errors:
                print(f"  [错误] {error}")
        check(report.ok, "示例工作流校验通过")
        check(
            report.order == ["n1", "n2", "n3", "n4", "n5", "n6", "n7"],
            f"拓扑顺序 {report.order}",
        )

        results = run(report.workflow, registry)
        model = results["n3"].outputs["model"]
        check(isinstance(model, PredictorModel), "训练出的模型满足 PredictorModel 契约")

        predicted = results["n5"].outputs["predictions"]
        check(len(predicted) == 40, f"测试集 40 行（200 行的 20%），实际 {len(predicted)}")

        metrics = results["n6"].outputs["metrics"].set_index("metric")["value"]
        check(float(metrics["r2"]) > 0.98, f"R2 = {float(metrics['r2']):.4f} > 0.98")
        check(float(metrics["rmse"]) < 1.0, f"RMSE = {float(metrics['rmse']):.4f} < 1.0")

        out_file = out_dir / "regression_out.csv"
        check(out_file.is_file(), f"SaveCSV 写出 {out_file.name}")
        written = out_file.read_text(encoding="utf-8").strip().splitlines()
        check(len(written) == 6, f"写出指标表 {len(written)} 行（表头 + 5 行指标）")

        mismatch = json.loads(json.dumps(raw))
        mismatch["nodes"][4]["inputs"]["model"] = {"from": "n1", "port": "table"}
        expect_error(registry, mismatch, "类型不匹配", "把 table 接到 model 端口")

        bad_port = json.loads(json.dumps(raw))
        bad_port["nodes"][1]["inputs"]["data"] = {"from": "n1", "port": "nope"}
        expect_error(registry, bad_port, "没有输出端口", "引用不存在的输出端口")

        cyclic = json.loads(json.dumps(raw))
        cyclic["nodes"][1]["inputs"]["data"] = {"from": "n5", "port": "predictions"}
        expect_error(registry, cyclic, "环", "构造 n2 <-> n5 的环")

        print("\nALL OK")
        return 0
    finally:
        if saved_workspace is None:
            os.environ.pop("workspace", None)
        else:
            os.environ["workspace"] = saved_workspace
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
