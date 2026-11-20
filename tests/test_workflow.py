"""engine.workflow 工作流校验测试。

直接运行：python tests/test_workflow.py
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.errors import WorkflowError
from engine.registry import Registry
from engine.workflow import load_workflow, validate

from _harness import check, expect_raises, run_cases


_REGISTRY = None


def get_registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = Registry().load(ROOT / "plugins")
    return _REGISTRY


def node(node_id, plugin, component, config=None, inputs=None):
    return {
        "id": node_id,
        "plugin": plugin,
        "component": component,
        "config": {} if config is None else config,
        "inputs": {} if inputs is None else inputs,
    }


def expect_error(report, *fragments):
    check(not report.ok, "期望校验失败，实际校验通过")
    text = "；".join(report.errors)
    for fragment in fragments:
        check(fragment in text, f"错误信息缺少 {fragment!r}，实际错误：{report.errors}")


def expect_warning(report, *fragments):
    text = "；".join(report.warnings)
    for fragment in fragments:
        check(fragment in text, f"警告信息缺少 {fragment!r}，实际警告：{report.warnings}")


def case_demo_valid():
    raw = load_workflow(ROOT / "workflows" / "linreg_demo.json")
    report = validate(get_registry(), raw)
    check(report.ok, f"linreg_demo.json 应校验通过，实际错误：{report.errors}")
    check(report.warnings == [], f"linreg_demo.json 不应有警告：{report.warnings}")
    check(
        report.order == ["n1", "n2", "n3", "n4"],
        f"拓扑顺序不对：{report.order}",
    )
    check(report.workflow is not None, "校验通过时应生成 Workflow")
    n3 = report.workflow.nodes["n3"]
    check(
        (n3.plugin, n3.component) == ("core", "PredictModel"),
        f"n3 应为 core.PredictModel，实际 {n3.plugin}.{n3.component}",
    )


def case_predict_model_ports():
    registry = get_registry()
    entry = registry.get_component("core", "PredictModel")
    check(entry is not None, "core.PredictModel 应存在")
    check(
        entry.input_schema["model"]["types"] == ["std_1.0@model"],
        f"model 端口类型不对：{entry.input_schema['model']}",
    )
    check(
        entry.input_schema["data"]["types"] == ["std_1.0@table"],
        f"data 端口类型不对：{entry.input_schema['data']}",
    )
    check(
        entry.output_schema["predictions"]["type"] == "std_1.0@table",
        f"输出端口类型不对：{entry.output_schema}",
    )


def case_unknown_top_field():
    raw = {
        "name": "t",
        "nodes": [node("n1", "linreg", "MakeLinearData")],
        "extra": 1,
    }
    report = validate(get_registry(), raw)
    expect_error(report, "未知字段", "extra")


def case_node_unknown_field():
    bad = node("n1", "linreg", "MakeLinearData")
    bad["bogus"] = 1
    report = validate(get_registry(), {"name": "t", "nodes": [bad]})
    expect_error(report, "未知字段", "bogus")


def case_duplicate_id():
    raw = {
        "name": "t",
        "nodes": [
            node("n1", "linreg", "MakeLinearData"),
            node("n1", "linreg", "MakeLinearData"),
        ],
    }
    report = validate(get_registry(), raw)
    expect_error(report, "id 重复")


def case_component_not_found():
    raw = {"name": "t", "nodes": [node("n1", "nope", "Nope")]}
    report = validate(get_registry(), raw)
    expect_error(report, "组件 nope.Nope 不存在")


def case_input_port_not_found():
    n1 = node(
        "n1",
        "linreg",
        "MakeLinearData",
        inputs={"bogus": {"from": "n1", "port": "data"}},
    )
    report = validate(get_registry(), {"name": "t", "nodes": [n1]})
    expect_error(report, "组件没有这个输入端口")


def case_output_port_not_found():
    nodes = [
        node("n1", "linreg", "MakeLinearData"),
        node(
            "n2",
            "core",
            "PredictModel",
            inputs={
                "model": {"from": "n1", "port": "nope"},
                "data": {"from": "n1", "port": "data"},
            },
        ),
    ]
    report = validate(get_registry(), {"name": "t", "nodes": nodes})
    expect_error(report, "没有输出端口 nope")


def case_type_mismatch():
    nodes = [
        node("n1", "linreg", "MakeLinearData"),
        node(
            "n2",
            "core",
            "PredictModel",
            inputs={
                "model": {"from": "n1", "port": "data"},
                "data": {"from": "n1", "port": "data"},
            },
        ),
    ]
    report = validate(get_registry(), {"name": "t", "nodes": nodes})
    expect_error(report, "类型不匹配")


def case_required_input_missing():
    nodes = [node("n1", "linreg", "FitLinearRegression")]
    report = validate(get_registry(), {"name": "t", "nodes": nodes})
    expect_error(report, "缺少必填输入", "data")


def case_source_node_missing():
    nodes = [
        node(
            "n1",
            "linreg",
            "FitLinearRegression",
            inputs={"data": {"from": "ghost", "port": "data"}},
        )
    ]
    report = validate(get_registry(), {"name": "t", "nodes": nodes})
    expect_error(report, "来源节点 ghost 不存在")


def case_cycle():
    nodes = [
        node(
            "a",
            "core",
            "SelectColumns",
            config={"columns": "x"},
            inputs={"data": {"from": "b", "port": "table"}},
        ),
        node(
            "b",
            "core",
            "SelectColumns",
            config={"columns": "y"},
            inputs={"data": {"from": "a", "port": "table"}},
        ),
    ]
    report = validate(get_registry(), {"name": "t", "nodes": nodes})
    expect_error(report, "存在环")


def case_isolated_node_warning_only():
    raw = {"name": "t", "nodes": [node("n1", "linreg", "MakeLinearData")]}
    report = validate(get_registry(), raw)
    check(report.ok, f"孤立节点不应产生错误，实际错误：{report.errors}")
    expect_warning(report, "孤立节点", "n1")
    check(report.workflow is not None, "只有警告时应生成 Workflow")


def case_defaults_filled():
    raw = {"name": "t", "nodes": [node("n1", "linreg", "MakeLinearData")]}
    report = validate(get_registry(), raw)
    check(report.ok, f"校验应通过，实际错误：{report.errors}")
    config = report.workflow.nodes["n1"].config
    check(config.get("n_samples") == 200, f"n_samples 默认值没填上：{config}")
    check(config.get("noise") == 0.5, f"noise 默认值没填上：{config}")
    check(config.get("seed") == 42, f"seed 默认值没填上：{config}")


def case_config_value_invalid():
    raw = {
        "name": "t",
        "nodes": [node("n1", "linreg", "MakeLinearData", config={"n_samples": 1.5})],
    }
    report = validate(get_registry(), raw)
    expect_error(report, "需要整数")


def case_unknown_config_param():
    raw = {
        "name": "t",
        "nodes": [node("n1", "linreg", "MakeLinearData", config={"bogus": 1})],
    }
    report = validate(get_registry(), raw)
    expect_error(report, "未知参数", "bogus")


def case_config_not_dict():
    raw = {
        "name": "t",
        "nodes": [node("n1", "linreg", "MakeLinearData", config=[])],
    }
    report = validate(get_registry(), raw)
    expect_error(report, "config 必须是 JSON 对象")


def case_edge_unknown_field():
    nodes = [
        node("n1", "linreg", "MakeLinearData"),
        node(
            "n2",
            "linreg",
            "FitLinearRegression",
            inputs={"data": {"from": "n1", "port": "data", "extra": 1}},
        ),
    ]
    report = validate(get_registry(), {"name": "t", "nodes": nodes})
    expect_error(report, "未知字段", "extra")


def case_nodes_not_list():
    report = validate(get_registry(), {"name": "t", "nodes": {}})
    expect_error(report, "nodes 必须是非空数组")


def case_name_not_string():
    for bad in (123, 0, False, None, ["x"]):
        raw = {
            "name": bad,
            "nodes": [node("n1", "linreg", "MakeLinearData")],
        }
        report = validate(get_registry(), raw)
        expect_error(report, "name 必须是字符串")


def case_load_workflow_errors():
    expect_raises(
        WorkflowError, lambda: load_workflow(ROOT / "workflows" / "nope.json"), "不存在"
    )
    with tempfile.TemporaryDirectory(prefix="engine_workflow_test_") as tmp:
        bad = Path(tmp) / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        expect_raises(WorkflowError, lambda: load_workflow(bad), "不是合法 JSON")


def case_bom_json():
    raw = {"name": "t", "nodes": [node("n1", "linreg", "MakeLinearData")]}
    with tempfile.TemporaryDirectory(prefix="engine_workflow_test_") as tmp:
        path = Path(tmp) / "bom.json"
        path.write_bytes(
            b"\xef\xbb\xbf" + json.dumps(raw, ensure_ascii=False).encode("utf-8")
        )
        loaded = load_workflow(path)
        check(loaded["name"] == "t", f"带 BOM 的 JSON 读取结果不对：{loaded!r}")
        report = validate(get_registry(), loaded)
        check(report.ok, f"带 BOM 的工作流应校验通过，实际错误：{report.errors}")


def case_gbk_json():
    with tempfile.TemporaryDirectory(prefix="engine_workflow_test_") as tmp:
        path = Path(tmp) / "gbk.json"
        path.write_bytes('{"name": "中文工作流", "nodes": []}'.encode("gbk"))
        expect_raises(WorkflowError, lambda: load_workflow(path), "不是 UTF-8 编码")


def case_env_valid():
    raw = {
        "name": "t",
        "env": {"A": "1"},
        "nodes": [node("n1", "linreg", "MakeLinearData")],
    }
    report = validate(get_registry(), raw)
    check(report.ok, f"合法 env 应校验通过，实际错误：{report.errors}")
    check(report.workflow is not None, "校验通过时应生成 Workflow")
    check(
        report.workflow.env == {"A": "1"},
        f"Workflow.env 不对：{report.workflow.env!r}",
    )


def case_env_not_object():
    raw = {
        "name": "t",
        "env": [],
        "nodes": [node("n1", "linreg", "MakeLinearData")],
    }
    report = validate(get_registry(), raw)
    expect_error(report, "env 必须是对象")


def case_env_bad_name():
    raw = {
        "name": "t",
        "env": {"1BAD": "x"},
        "nodes": [node("n1", "linreg", "MakeLinearData")],
    }
    report = validate(get_registry(), raw)
    expect_error(report, "env 变量名不合法", "1BAD")


def case_env_bad_value_type():
    for bad in (1, True):
        raw = {
            "name": "t",
            "env": {"A": bad},
            "nodes": [node("n1", "linreg", "MakeLinearData")],
        }
        report = validate(get_registry(), raw)
        expect_error(report, "env.A 的值必须是字符串")


CASES = [
    ("linreg_demo.json 校验通过且顺序正确", case_demo_valid),
    ("core.PredictModel 端口类型", case_predict_model_ports),
    ("未知顶层字段", case_unknown_top_field),
    ("节点未知字段", case_node_unknown_field),
    ("节点 id 重复", case_duplicate_id),
    ("节点引用不存在的组件", case_component_not_found),
    ("输入端口不存在", case_input_port_not_found),
    ("输出端口不存在", case_output_port_not_found),
    ("端口类型不匹配", case_type_mismatch),
    ("必填输入缺失", case_required_input_missing),
    ("来源节点不存在", case_source_node_missing),
    ("构造环", case_cycle),
    ("孤立节点只警告不报错", case_isolated_node_warning_only),
    ("config 默认值被填上", case_defaults_filled),
    ("config 取值不合法", case_config_value_invalid),
    ("config 未知参数", case_unknown_config_param),
    ("config 不是对象", case_config_not_dict),
    ("env 合法对象通过并保留", case_env_valid),
    ("env 不是对象", case_env_not_object),
    ("env 变量名不合法", case_env_bad_name),
    ("env 值必须是字符串", case_env_bad_value_type),
    ("连线未知字段", case_edge_unknown_field),
    ("nodes 不是非空数组", case_nodes_not_list),
    ("name 不是字符串", case_name_not_string),
    ("工作流文件读取错误", case_load_workflow_errors),
    ("带 BOM 的 JSON 能正常加载", case_bom_json),
    ("GBK 编码的 JSON 报明确错误", case_gbk_json),
]


def main():
    return run_cases("workflow", CASES)


if __name__ == "__main__":
    sys.exit(main())
