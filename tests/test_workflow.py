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
from engine.workflow import load_workflow, validate

from _harness import check, expect_raises, get_registry, node, run_cases, run_workflow


def source_node(node_id, extra_config=None):
    """插件层不再有造数据组件，无输入的源节点统一是 fileio.LoadCSV。

    validate 只校验 path 是字符串、不读文件，所以这里用一个占位路径即可。
    """
    config = {"path": "data.csv"}
    config.update(extra_config or {})
    return node(node_id, "fileio", "LoadCSV", config=config)


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
    raw = load_workflow(ROOT / "workflows" / "regression_demo.json")
    report = validate(get_registry(), raw)
    check(report.ok, f"regression_demo.json 应校验通过，实际错误：{report.errors}")
    check(report.warnings == [], f"regression_demo.json 不应有警告：{report.warnings}")
    check(
        report.order == ["n1", "n2", "n3", "n4", "n5", "n6", "n7"],
        f"拓扑顺序不对：{report.order}",
    )
    check(report.workflow is not None, "校验通过时应生成 Workflow")
    n2 = report.workflow.nodes["n2"]
    check(
        (n2.plugin, n2.component) == ("split", "SplitTable"),
        f"n2 应为 split.SplitTable，实际 {n2.plugin}.{n2.component}",
    )
    n4 = report.workflow.nodes["n4"]
    check(
        (n4.plugin, n4.component) == ("split", "SplitXY"),
        f"n4 应为 split.SplitXY，实际 {n4.plugin}.{n4.component}",
    )
    n5 = report.workflow.nodes["n5"]
    check(
        (n5.plugin, n5.component) == ("core", "PredictModel"),
        f"n5 应为 core.PredictModel，实际 {n5.plugin}.{n5.component}",
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
        "nodes": [source_node("n1")],
        "extra": 1,
    }
    report = validate(get_registry(), raw)
    expect_error(report, "未知字段", "extra")


def case_node_unknown_field():
    bad = source_node("n1")
    bad["bogus"] = 1
    report = validate(get_registry(), {"name": "t", "nodes": [bad]})
    expect_error(report, "未知字段", "bogus")


def case_duplicate_id():
    raw = {
        "name": "t",
        "nodes": [
            source_node("n1"),
            source_node("n1"),
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
        "table",
        "SelectColumns",
        config={"columns": ["x"]},
        inputs={"bogus": {"from": "n1", "port": "table"}},
    )
    report = validate(get_registry(), {"name": "t", "nodes": [n1]})
    expect_error(report, "组件没有这个输入端口")


def case_output_port_not_found():
    nodes = [
        source_node("n1"),
        node(
            "n2",
            "core",
            "PredictModel",
            inputs={
                "model": {"from": "n1", "port": "nope"},
                "data": {"from": "n1", "port": "table"},
            },
        ),
    ]
    report = validate(get_registry(), {"name": "t", "nodes": nodes})
    expect_error(report, "没有输出端口 nope")


def case_type_mismatch():
    nodes = [
        source_node("n1"),
        node(
            "n2",
            "core",
            "PredictModel",
            inputs={
                "model": {"from": "n1", "port": "table"},
                "data": {"from": "n1", "port": "table"},
            },
        ),
    ]
    report = validate(get_registry(), {"name": "t", "nodes": nodes})
    expect_error(report, "类型不匹配")


def case_required_input_missing():
    nodes = [
        node(
            "n1",
            "ml",
            "LinearRegression",
            config={"feature": ["x"], "target": "y"},
        )
    ]
    report = validate(get_registry(), {"name": "t", "nodes": nodes})
    expect_error(report, "缺少必填输入", "data")


def case_source_node_missing():
    nodes = [
        node(
            "n1",
            "ml",
            "LinearRegression",
            config={"feature": ["x"], "target": "y"},
            inputs={"data": {"from": "ghost", "port": "data"}},
        )
    ]
    report = validate(get_registry(), {"name": "t", "nodes": nodes})
    expect_error(report, "来源节点 ghost 不存在")


def case_cycle():
    nodes = [
        node(
            "a",
            "table",
            "SelectColumns",
            config={"columns": ["x"]},
            inputs={"data": {"from": "b", "port": "table"}},
        ),
        node(
            "b",
            "table",
            "SelectColumns",
            config={"columns": ["y"]},
            inputs={"data": {"from": "a", "port": "table"}},
        ),
    ]
    report = validate(get_registry(), {"name": "t", "nodes": nodes})
    expect_error(report, "存在环")


def case_isolated_node_warning_only():
    raw = {"name": "t", "nodes": [source_node("n1")]}
    report = validate(get_registry(), raw)
    check(report.ok, f"孤立节点不应产生错误，实际错误：{report.errors}")
    expect_warning(report, "孤立节点", "n1")
    check(report.workflow is not None, "只有警告时应生成 Workflow")


def case_defaults_filled():
    raw = {"name": "t", "nodes": [source_node("n1")]}
    report = validate(get_registry(), raw)
    check(report.ok, f"校验应通过，实际错误：{report.errors}")
    config = report.workflow.nodes["n1"].config
    check(config.get("encoding") == "utf-8", f"encoding 默认值没填上：{config}")
    check(config.get("sep") == ",", f"sep 默认值没填上：{config}")
    check(config.get("header") is True, f"header 默认值没填上：{config}")


def case_config_value_invalid():
    raw = {
        "name": "t",
        "nodes": [source_node("n1", {"path": 1.5})],
    }
    report = validate(get_registry(), raw)
    expect_error(report, "需要字符串")


def case_unknown_config_param():
    raw = {
        "name": "t",
        "nodes": [source_node("n1", {"bogus": 1})],
    }
    report = validate(get_registry(), raw)
    expect_error(report, "未知参数", "bogus")


def case_config_not_dict():
    raw = {
        "name": "t",
        "nodes": [node("n1", "fileio", "LoadCSV", config=[])],
    }
    report = validate(get_registry(), raw)
    expect_error(report, "config 必须是 JSON 对象")


def case_edge_unknown_field():
    nodes = [
        source_node("n1"),
        node(
            "n2",
            "ml",
            "LinearRegression",
            config={"feature": ["x"], "target": "y"},
            inputs={"data": {"from": "n1", "port": "table", "extra": 1}},
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
            "nodes": [source_node("n1")],
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
    raw = {"name": "t", "nodes": [source_node("n1")]}
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
        "nodes": [source_node("n1")],
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
        "nodes": [source_node("n1")],
    }
    report = validate(get_registry(), raw)
    expect_error(report, "env 必须是对象")


def case_env_bad_name():
    raw = {
        "name": "t",
        "env": {"1BAD": "x"},
        "nodes": [source_node("n1")],
    }
    report = validate(get_registry(), raw)
    expect_error(report, "env 变量名不合法", "1BAD")


def case_env_bad_value_type():
    for bad in (1, True):
        raw = {
            "name": "t",
            "env": {"A": bad},
            "nodes": [source_node("n1")],
        }
        report = validate(get_registry(), raw)
        expect_error(report, "env.A 的值必须是字符串")


def case_addition_object_valid_and_runs():
    """顶层 addition 是编辑器私有区：校验通过，执行也不受影响。"""
    with tempfile.TemporaryDirectory(prefix="engine_workflow_test_") as tmp:
        path = Path(tmp) / "data.csv"
        path.write_text("x\n1\n2\n", encoding="utf-8")
        raw = {
            "name": "addition",
            "nodes": [source_node("n1", {"path": str(path)})],
            "addition": {
                "client": "workflow-studio",
                "version": 1,
                "positions": {"n1": {"x": 80, "y": 60}},
                "groups": [{"id": "g1", "title": "组", "nodes": ["n1"]}],
            },
        }
        report = validate(get_registry(), raw)
        check(report.ok, f"带 addition 对象应校验通过：{report.errors}")
        results = run_workflow(get_registry(), raw)
    check(results["n1"].outputs["table"] is not None, "带 addition 对象应能正常执行")


def case_addition_non_object_still_valid():
    """引擎只承认字段存在、不校验类型：字符串和数字都照样通过。"""
    for value in ("editor-private", 42):
        raw = {"name": "t", "nodes": [source_node("n1")], "addition": value}
        report = validate(get_registry(), raw)
        check(report.ok, f"addition={value!r} 不应报错：{report.errors}")


def case_addition_typo_is_unknown():
    raw = {"name": "t", "nodes": [source_node("n1")], "aditon": {}}
    report = validate(get_registry(), raw)
    expect_error(report, "未知字段", "aditon")


def case_node_level_addition_rejected():
    """addition 只放行顶层；节点白名单没有跟着变松。"""
    bad = source_node("n1")
    bad["addition"] = {"x": 1}
    report = validate(get_registry(), {"name": "t", "nodes": [bad]})
    expect_error(report, "未知字段", "addition")


CASES = [
    ("regression_demo.json 校验通过且顺序正确", case_demo_valid),
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
    ("addition 对象通过且能执行", case_addition_object_valid_and_runs),
    ("addition 字符串/数字也通过（不校验类型）", case_addition_non_object_still_valid),
    ("addition 拼错仍报未知字段", case_addition_typo_is_unknown),
    ("节点级 addition 仍报未知字段", case_node_level_addition_rejected),
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
