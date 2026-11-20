"""engine.runner 执行器测试（用临时插件记录行为）。

直接运行：python tests/test_runner.py
"""

import gc
import importlib
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.api import PredictorModel
from engine.errors import ExecutionError
from engine.registry import Registry
from engine.runner import run
from engine.workflow import NodeSpec, Workflow, load_workflow, validate

from _harness import check, env_guard, expect_raises, run_cases, write_demo_data


_RUNNER_SOURCE = '''\
from engine.api import Component, PredictorModel

PLUGIN_NAME = "rnp1"
PLUGIN_VERSION = "1.0"
PLUGIN_TITLE = "runner 测试"
PLUGIN_TYPES = {"num": "数字"}


class Echo(Component):
    name = "Echo"

    @staticmethod
    def config_schema():
        return {}

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"value": {"type": "num"}}

    def __init__(self, config):
        pass

    def invoke(self):
        return {"value": 41}


class Sink(Component):
    name = "Sink"
    RECEIVED = []

    @staticmethod
    def config_schema():
        return {}

    @staticmethod
    def input_schema():
        return {"value": {"types": ["num"], "required": True}}

    @staticmethod
    def output_schema():
        return {"result": {"type": "num"}}

    def __init__(self, config):
        pass

    def invoke(self, value):
        Sink.RECEIVED.append(value)
        return {"result": value * 2}


class BoomInit(Component):
    name = "BoomInit"

    @staticmethod
    def config_schema():
        return {}

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"value": {"type": "num"}}

    def __init__(self, config):
        raise RuntimeError("初始化故意失败")

    def invoke(self):
        return {"value": 0}


class BoomInvoke(Component):
    name = "BoomInvoke"
    CLOSED = []

    @staticmethod
    def config_schema():
        return {}

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"value": {"type": "num"}}

    def __init__(self, config):
        pass

    def invoke(self):
        raise ValueError("执行故意失败")

    def close(self):
        BoomInvoke.CLOSED.append("closed")


class ReturnNonDict(Component):
    name = "ReturnNonDict"
    CLOSED = []

    @staticmethod
    def config_schema():
        return {}

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"value": {"type": "num"}}

    def __init__(self, config):
        pass

    def invoke(self):
        return [1, 2]

    def close(self):
        ReturnNonDict.CLOSED.append("closed")


class MissingPort(Component):
    name = "MissingPort"

    @staticmethod
    def config_schema():
        return {}

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"a": {"type": "num"}, "b": {"type": "num"}}

    def __init__(self, config):
        pass

    def invoke(self):
        return {"a": 1}


class ExtraPort(Component):
    name = "ExtraPort"

    @staticmethod
    def config_schema():
        return {}

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"a": {"type": "num"}}

    def __init__(self, config):
        pass

    def invoke(self):
        return {"a": 1, "b": 2}


class CloserOK(Component):
    name = "CloserOK"
    CLOSED = []

    @staticmethod
    def config_schema():
        return {}

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"value": {"type": "num"}}

    def __init__(self, config):
        pass

    def invoke(self):
        return {"value": 1}

    def close(self):
        CloserOK.CLOSED.append("closed")


class BadModel(Component):
    name = "BadModel"

    @staticmethod
    def config_schema():
        return {}

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"model": {"type": "std_1.0@model"}}

    def __init__(self, config):
        pass

    def invoke(self):
        return {"model": object()}


class _GoodPredictor(PredictorModel):
    def predict(self, frame):
        return [0.0] * len(frame)


class GoodModel(Component):
    name = "GoodModel"

    @staticmethod
    def config_schema():
        return {}

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"model": {"type": "std_1.0@model"}}

    def __init__(self, config):
        pass

    def invoke(self):
        return {"model": _GoodPredictor()}


COMPONENTS = [Echo, Sink, BoomInit, BoomInvoke, ReturnNonDict,
              MissingPort, ExtraPort, CloserOK, BadModel, GoodModel]
'''

_TEMP_DIR = None
_REGISTRY = None


def get_registry():
    global _TEMP_DIR, _REGISTRY
    if _REGISTRY is None:
        _TEMP_DIR = tempfile.TemporaryDirectory(prefix="engine_runner_test_")
        zip_path = Path(_TEMP_DIR.name) / "rnp1.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("rnp1/__init__.py", "")
            archive.writestr("rnp1/components.py", _RUNNER_SOURCE)
        _REGISTRY = Registry().load(_TEMP_DIR.name)
    return _REGISTRY


def _release_zip(zip_str):
    """释放导入系统与 importlib.metadata 留下的 zip 句柄，否则 Windows 删不掉。"""
    while zip_str in sys.path:
        sys.path.remove(zip_str)
    for name in [n for n in sys.modules if n == "rnp1" or n.startswith("rnp1.")]:
        del sys.modules[name]
    importlib.invalidate_caches()
    for obj in gc.get_objects():
        if isinstance(obj, zipfile.ZipFile) and str(obj.filename) == zip_str:
            try:
                obj.close()
            except Exception:
                pass
    gc.collect()


def cleanup():
    global _TEMP_DIR, _REGISTRY
    if _TEMP_DIR is not None:
        zip_str = str((Path(_TEMP_DIR.name) / "rnp1.zip").resolve())
        _release_zip(zip_str)
        _TEMP_DIR.cleanup()
        _TEMP_DIR = None
    _REGISTRY = None


def plugin_class(component):
    entry = get_registry().get_component("rnp1", component)
    check(entry is not None, f"组件 rnp1.{component} 未注册")
    return entry.cls


def build_workflow(nodes):
    """nodes: [(node_id, component, {端口: (来源节点, 来源端口)})]"""
    registry = get_registry()
    specs = {}
    order = []
    for node_id, component, inputs in nodes:
        entry = registry.get_component("rnp1", component)
        check(entry is not None, f"组件 rnp1.{component} 未注册")
        specs[node_id] = NodeSpec(node_id, "rnp1", component, {}, inputs, entry)
        order.append(node_id)
    return Workflow(name="runner_case", nodes=specs, order=order)


def case_init_failure():
    workflow = build_workflow([("bad1", "BoomInit", {})])
    expect_raises(
        ExecutionError,
        lambda: run(workflow, get_registry()),
        "bad1",
        "初始化失败",
    )


def case_invoke_non_dict():
    plugin_class("ReturnNonDict").CLOSED.clear()
    workflow = build_workflow([("n1", "ReturnNonDict", {})])
    expect_raises(
        ExecutionError, lambda: run(workflow, get_registry()), "n1", "必须返回 dict"
    )


def case_missing_output_port():
    workflow = build_workflow([("n1", "MissingPort", {})])
    expect_raises(
        ExecutionError,
        lambda: run(workflow, get_registry()),
        "返回端口不匹配",
        "缺少",
        "b",
    )


def case_extra_output_port():
    workflow = build_workflow([("n1", "ExtraPort", {})])
    expect_raises(
        ExecutionError,
        lambda: run(workflow, get_registry()),
        "返回端口不匹配",
        "多余",
        "b",
    )


def case_upstream_passed_downstream():
    plugin_class("Sink").RECEIVED.clear()
    workflow = build_workflow(
        [
            ("n1", "Echo", {}),
            ("n2", "Sink", {"value": ("n1", "value")}),
        ]
    )
    results = run(workflow, get_registry())
    check(
        plugin_class("Sink").RECEIVED == [41],
        f"下游收到的值不对：{plugin_class('Sink').RECEIVED}",
    )
    check(results["n1"].outputs == {"value": 41}, f"上游输出不对：{results['n1'].outputs}")
    check(
        results["n2"].outputs == {"result": 82},
        f"下游输出不对：{results['n2'].outputs}",
    )
    check(results["n1"].ms >= 0, f"耗时不能为负：{results['n1'].ms}")


def case_close_on_success():
    plugin_class("CloserOK").CLOSED.clear()
    workflow = build_workflow([("n1", "CloserOK", {})])
    run(workflow, get_registry())
    check(
        plugin_class("CloserOK").CLOSED == ["closed"],
        f"成功路径 close 调用次数不对：{plugin_class('CloserOK').CLOSED}",
    )


def case_close_on_invoke_failure():
    plugin_class("BoomInvoke").CLOSED.clear()
    workflow = build_workflow([("n1", "BoomInvoke", {})])
    expect_raises(ExecutionError, lambda: run(workflow, get_registry()), "执行失败")
    check(
        plugin_class("BoomInvoke").CLOSED == ["closed"],
        f"失败路径 close 没调用：{plugin_class('BoomInvoke').CLOSED}",
    )


def case_close_on_output_check_failure():
    plugin_class("ReturnNonDict").CLOSED.clear()
    workflow = build_workflow([("n1", "ReturnNonDict", {})])
    expect_raises(ExecutionError, lambda: run(workflow, get_registry()), "必须返回 dict")
    check(
        plugin_class("ReturnNonDict").CLOSED == ["closed"],
        f"输出校验失败时 close 没调用：{plugin_class('ReturnNonDict').CLOSED}",
    )


def case_close_when_later_init_fails():
    plugin_class("CloserOK").CLOSED.clear()
    workflow = build_workflow(
        [
            ("n1", "CloserOK", {}),
            ("n2", "BoomInit", {}),
        ]
    )
    expect_raises(ExecutionError, lambda: run(workflow, get_registry()), "n2")
    check(
        plugin_class("CloserOK").CLOSED == ["closed"],
        f"后续节点初始化失败时，已创建实例没有被 close："
        f"{plugin_class('CloserOK').CLOSED}",
    )


def case_model_contract_violation():
    """输出声称 std_1.0@model 但载体没继承 PredictorModel → 执行期报错。"""
    workflow = build_workflow([("n1", "BadModel", {})])
    expect_raises(
        ExecutionError,
        lambda: run(workflow, get_registry()),
        "n1",
        "输出端口 model",
        "没有继承 PredictorModel",
        "predict",
    )


def case_model_contract_satisfied():
    workflow = build_workflow([("n1", "GoodModel", {})])
    results = run(workflow, get_registry())
    value = results["n1"].outputs["model"]
    check(isinstance(value, PredictorModel), f"模型应继承 PredictorModel：{type(value).__name__}")


def case_end_to_end_demo():
    """regression_demo：读 CSV → 切分 → SplitXY → 训练 → 预测 → 评估 → 存盘。

    ${workspace} 指向临时目录：n1 读那里的 data.csv，n7 往那里写 regression_out.csv，
    不往工程根目录落文件。
    """
    registry = Registry().load(ROOT / "plugins")
    with tempfile.TemporaryDirectory(prefix="engine_runner_demo_") as tmp, env_guard():
        os.environ["workspace"] = tmp
        write_demo_data(tmp)
        raw = load_workflow(ROOT / "workflows" / "regression_demo.json")
        report = validate(registry, raw)
        check(report.ok, f"示例工作流应校验通过：{report.errors}")

        results = run(report.workflow, registry)
        model = results["n3"].outputs["model"]
        check(
            isinstance(model, PredictorModel),
            f"ml 模型应继承 PredictorModel：{type(model).__name__}",
        )
        predictions = results["n5"].outputs["predictions"]
        check(
            "y_pred" in predictions.columns,
            f"预测列应存在：{list(predictions.columns)}",
        )
        metrics = results["n6"].outputs["metrics"].set_index("metric")["value"]
        r2 = float(metrics["r2"])
        check(r2 > 0.95, f"R² = {r2:.4f} 应 > 0.95")
        check(
            (Path(tmp) / "regression_out.csv").is_file(),
            "SaveCSV 应把指标表写到 ${workspace} 下",
        )
        check(results["n7"].outputs == {}, "SaveCSV 返回空输出应被接受")


CASES = [
    ("初始化抛异常 -> ExecutionError 含节点 id", case_init_failure),
    ("invoke 返回非 dict 报错", case_invoke_non_dict),
    ("返回少一个端口报错", case_missing_output_port),
    ("返回多一个端口报错", case_extra_output_port),
    ("上游输出传给下游入参", case_upstream_passed_downstream),
    ("成功路径 close 被调用", case_close_on_success),
    ("invoke 失败路径 close 被调用", case_close_on_invoke_failure),
    ("输出校验失败路径 close 被调用", case_close_on_output_check_failure),
    ("后续初始化失败时已创建实例被 close", case_close_when_later_init_fails),
    ("模型没继承 PredictorModel → 执行期报错", case_model_contract_violation),
    ("模型继承 PredictorModel → 通过", case_model_contract_satisfied),
    ("端到端：训练 → 通用预测 → 评估", case_end_to_end_demo),
]


def main():
    try:
        return run_cases("runner", CASES)
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
