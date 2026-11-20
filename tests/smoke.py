"""一条命令跑完 P1 全链路：打包插件 -> 加载 -> 校验 -> 执行 -> 断言。

    python tests/smoke.py

临时 zip 打在系统临时目录，跑完清理，不往仓库里丢东西。
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.registry import Registry  # noqa: E402
from engine.runner import run  # noqa: E402
from engine.workflow import validate  # noqa: E402
from tools.build_plugins import build_all  # noqa: E402

WORKFLOW = ROOT / "workflows" / "linreg_demo.json"


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


def main():
    temp = Path(tempfile.mkdtemp(prefix="wf_smoke_"))
    try:
        built = build_all(temp)
        check(len(built) == 2, f"打包出 {len(built)} 个插件")

        registry = Registry().load(temp)
        check(sorted(registry.plugins) == ["core", "linreg", "std"], f"插件集合 {sorted(registry.plugins)}")
        check(len(registry.components) == 6, f"组件数 {len(registry.components)}")
        check("std_1.0@model" in registry.types, "标准模型类型已注册")
        check("std_1.0@table" in registry.types, "标准表格类型已注册")
        check("std_1.0@model" in registry.models, "标准模型类型已绑定 PredictorModel")

        raw = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        report = validate(registry, raw)
        if not report.ok:
            for error in report.errors:
                print(f"  [错误] {error}")
        check(report.ok, "示例工作流校验通过")
        check(report.order == ["n1", "n2", "n3", "n4"], f"拓扑顺序 {report.order}")

        results = run(report.workflow, registry)
        model = results["n2"].outputs["model"]
        check(abs(model.coef - 2.0) <= 0.05, f"拟合斜率 {model.coef:.4f} ≈ 2.0")
        # n=200、noise=0.5 时截距标准误约 0.07，留 0.3 容差（约 4σ）
        check(abs(model.intercept - 1.0) <= 0.3, f"拟合截距 {model.intercept:.4f} ≈ 1.0")
        metrics = results["n4"].outputs["metrics"].set_index("metric")["value"]
        check(float(metrics["r2"]) > 0.95, f"R2 = {float(metrics['r2']):.4f} > 0.95")

        mismatch = json.loads(json.dumps(raw))
        mismatch["nodes"][2]["inputs"]["model"] = {"from": "n1", "port": "data"}
        expect_error(registry, mismatch, "类型不匹配", "把 table 接到 model 端口")

        bad_port = json.loads(json.dumps(raw))
        bad_port["nodes"][1]["inputs"]["data"] = {"from": "n1", "port": "nope"}
        expect_error(registry, bad_port, "没有输出端口", "引用不存在的输出端口")

        cyclic = json.loads(json.dumps(raw))
        cyclic["nodes"][1]["inputs"]["data"] = {"from": "n3", "port": "predictions"}
        expect_error(registry, cyclic, "环", "构造 n2 <-> n3 的环")

        print("\nALL OK")
        return 0
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
