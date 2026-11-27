"""studio.contract 校验器的契约测试。

直接运行：python tests/test_contract.py
"""

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.registry import Registry
from studio.contract import (
    ContractError,
    check_file,
    check_health,
    check_path_result,
    check_plugins,
    check_project,
    check_run,
    check_stat,
    check_tree,
    check_validate,
    check_write_file,
)
from studio.project import Project
from studio.server import EngineService

from _harness import DEMO_WORKFLOW, check, expect_raises, run_cases, write_demo_data

DEMO = DEMO_WORKFLOW


# ---- 载荷构造 ----

def health_payload():
    return {"ok": True, "engine": "0.1.0", "plugins": 2, "components": 6}


def component_payload():
    return {
        "name": "Comp",
        "title": "组件",
        "desc": "",
        "config_schema": {"p": {"type": "string"}},
        "input_schema": {
            "data": {
                "types": ["std_1.0@table"],
                "type_labels": ["std@table"],
                "required": True,
                "title": "数据",
                "desc": "",
            }
        },
        "output_schema": {
            "out": {
                "type": "std_1.0@table",
                "type_label": "std@table",
                "title": "",
                "desc": "",
            }
        },
    }


def plugins_payload():
    return {
        "plugins": [
            {
                "name": "core",
                "version": "1.0",
                "title": "基础",
                "types": [{"id": "std_1.0@table", "desc": "表"}],
                "components": [component_payload()],
            }
        ]
    }


def report_payload(ok=True, errors=None, warnings=None, order=None):
    return {
        "ok": ok,
        "errors": [] if errors is None else errors,
        "warnings": [] if warnings is None else warnings,
        "order": [] if order is None else order,
    }


def run_payload():
    payload = report_payload(ok=True, order=["n1"])
    payload["nodes"] = [
        {
            "id": "n1",
            "component": "ml.LinearRegression",
            "ms": 1.5,
            "outputs": {},
            "error": None,
        }
    ]
    return payload


# ---- check_health ----

def case_health_rejects():
    base = health_payload()
    for value in (1, "true", False):
        payload = copy.deepcopy(base)
        payload["ok"] = value
        expect_raises(ContractError, lambda p=payload: check_health(p), "health.ok")

    payload = copy.deepcopy(base)
    del payload["ok"]
    expect_raises(ContractError, lambda p=payload: check_health(p), "health.ok")

    payload = copy.deepcopy(base)
    payload["engine"] = 1
    expect_raises(ContractError, lambda p=payload: check_health(p), "health.engine")

    payload = copy.deepcopy(base)
    payload["plugins"] = "2"
    expect_raises(ContractError, lambda p=payload: check_health(p), "health.plugins")

    payload = copy.deepcopy(base)
    payload["components"] = True
    expect_raises(ContractError, lambda p=payload: check_health(p), "health.components")

    check(check_health(base) == base, "合法 health 载荷应通过")


# ---- check_plugins ----

def case_plugins_rejects():
    base = plugins_payload()

    expect_raises(ContractError, lambda: check_plugins({"plugins": "x"}), "必须是数组")

    payload = copy.deepcopy(base)
    payload["plugins"][0]["components"] = "x"
    expect_raises(ContractError, lambda p=payload: check_plugins(p), "components 必须是数组")

    payload = copy.deepcopy(base)
    payload["plugins"][0]["components"][0]["input_schema"]["data"]["type_labels"] = []
    expect_raises(ContractError, lambda p=payload: check_plugins(p), "type_labels 必须与 types 等长")

    payload = copy.deepcopy(base)
    del payload["plugins"][0]["components"][0]["output_schema"]["out"]["type_label"]
    expect_raises(ContractError, lambda p=payload: check_plugins(p), "type_label 必须是字符串")

    check(check_plugins(base) == base, "合法 plugins 载荷应通过")


# ---- check_validate ----

def case_validate_rejects():
    expect_raises(ContractError, 
        lambda: check_validate(report_payload(ok="true")), "字段 ok 必须是 bool"
    )
    expect_raises(ContractError, 
        lambda: check_validate(report_payload(errors=[1])), "字段 errors 必须是字符串数组"
    )
    expect_raises(ContractError, 
        lambda: check_validate(report_payload(ok=True, order=[])),
        "ok=true 时 order 不能为空",
    )
    expect_raises(ContractError, 
        lambda: check_validate(report_payload(ok=False, errors=[], order=[])),
        "ok=false 时必须给出至少一条 errors",
    )


def case_validate_accepts():
    good = report_payload(ok=True, order=["n1"])
    check(check_validate(good) == good, "校验通过载荷应通过")

    rejected = report_payload(ok=False, errors=["类型不匹配"], order=[])
    check(check_validate(rejected) == rejected, "校验拒绝载荷应通过")


# ---- check_run ----

def case_run_rejects():
    base = run_payload()

    payload = copy.deepcopy(base)
    payload["nodes"] = {}
    expect_raises(ContractError, lambda p=payload: check_run(p), "run.nodes 必须是数组")

    payload = copy.deepcopy(base)
    payload["nodes"][0]["ms"] = "1.5"
    expect_raises(ContractError, lambda p=payload: check_run(p), "ms 必须是数字")

    payload = copy.deepcopy(base)
    payload["nodes"][0]["ms"] = True
    expect_raises(ContractError, lambda p=payload: check_run(p), "ms 必须是数字")

    payload = copy.deepcopy(base)
    payload["nodes"][0]["outputs"] = "x"
    expect_raises(ContractError, lambda p=payload: check_run(p), "outputs 必须是 dict")

    payload = copy.deepcopy(base)
    payload["order"] = ["n1", "n2"]
    expect_raises(ContractError, lambda p=payload: check_run(p), "必须与 order 完全一致")


def case_run_accepts():
    good = run_payload()
    check(check_run(good) == good, "run 成功载荷应通过")

    failed = run_payload()
    failed["ok"] = False
    failed["errors"] = ["节点 n1 执行失败"]
    failed["nodes"][0]["error"] = "节点 n1 执行失败"
    check(check_run(failed) == failed, "run 失败载荷应通过")


# ---- 正向：真实服务返回的四个响应都能通过对应校验器 ----

def case_real_service_payloads():
    registry = Registry().load(ROOT / "plugins")
    # 直接构造服务时没有 studio 启动时注入的 workspace；demo 的 n1 从
    # ${workspace}/data.csv 读数据、n7 往那里写文件，所以用临时目录顶替。
    with tempfile.TemporaryDirectory(prefix="engine_contract_test_") as tmp:
        write_demo_data(tmp)
        service = EngineService(registry, {"workspace": tmp}, project=Project(tmp))

        health = service.health()
        check(check_health(health) == health, f"health 响应未通过契约：{health}")

        plugins = service.plugins()
        check(check_plugins(plugins) == plugins, "plugins 响应未通过契约")

        workflow = json.loads(DEMO.read_text(encoding="utf-8"))

        validated = service.validate(workflow)
        check(check_validate(validated) == validated, f"validate 响应未通过契约：{validated}")

        executed = service.run(workflow)
        check(executed["ok"] is True, f"示例工作流应执行成功：{executed.get('errors')}")
        check(check_run(executed) == executed, "run 成功响应未通过契约")

        broken = copy.deepcopy(workflow)
        broken["nodes"][5]["config"]["target"] = "nope"
        failed = service.run(broken)
        check(failed["ok"] is False, "坏列名应在执行期失败")
        check(check_run(failed) == failed, "run 失败响应未通过契约")

        stat = service.stat_file("data.csv")
        check(stat["kind"] == "file", f"stat 响应 kind=file：{stat}")
        check(check_stat(stat) == stat, "stat 响应未通过契约")


# ---- 项目与文件接口：check_project / check_tree / check_file / check_write_file / check_path_result ----

def case_project_accepts_and_rejects():
    good = {
        "ok": True,
        "errors": [],
        "root": r"C:\proj",
        "name": "proj",
        "launcher": None,
        "plugins": {"global": 5, "project": 0},
        "skipped": [],
    }
    check(check_project(good) == good, "project 合法载荷应通过")

    payload = copy.deepcopy(good)
    payload["root"] = ""
    expect_raises(
        ContractError, lambda: check_project(payload), "project.root 必须是非空字符串"
    )

    payload = copy.deepcopy(good)
    payload["plugins"]["global"] = True
    expect_raises(ContractError, lambda: check_project(payload), "非负整数")

    payload = copy.deepcopy(good)
    payload["skipped"] = [
        {"file": "x.zip", "path": "x.zip", "reason": "坏包", "source": "other"}
    ]
    expect_raises(
        ContractError, lambda: check_project(payload), "source 只能是 global 或 project"
    )


def case_tree_accepts_and_rejects():
    good = {
        "ok": True,
        "errors": [],
        "path": "",
        "entries": [
            {"name": "d", "path": "d", "kind": "dir"},
            {"name": "a.txt", "path": "a.txt", "kind": "file", "size": 3},
        ],
    }
    check(check_tree(good) == good, "tree 合法载荷应通过")

    payload = copy.deepcopy(good)
    payload["entries"][0]["kind"] = "link"
    expect_raises(ContractError, lambda: check_tree(payload), "kind 只能是 file 或 dir")

    payload = copy.deepcopy(good)
    payload["entries"][1]["size"] = True
    expect_raises(ContractError, lambda: check_tree(payload), "size 必须是非负整数")

    payload = copy.deepcopy(good)
    payload["entries"][1]["path"] = "../x"
    expect_raises(ContractError, lambda: check_tree(payload), "不能包含 ..")


def case_file_accepts_and_rejects():
    text = {
        "ok": True,
        "errors": [],
        "path": "a.txt",
        "kind": "text",
        "size": 3,
        "text": "abc",
    }
    binary = {
        "ok": True,
        "errors": [],
        "path": "b.bin",
        "kind": "binary",
        "size": 4,
        "text": None,
    }
    check(check_file(text) == text, "file text 载荷应通过")
    check(check_file(binary) == binary, "file binary 载荷应通过")

    payload = copy.deepcopy(text)
    payload["kind"] = "weird"
    expect_raises(
        ContractError,
        lambda: check_file(payload),
        "kind 只能是 text / binary / too_large",
    )

    payload = copy.deepcopy(binary)
    payload["text"] = "x"
    expect_raises(ContractError, lambda: check_file(payload), "text 必须是 null")

    payload = copy.deepcopy(text)
    payload["size"] = True
    expect_raises(ContractError, lambda: check_file(payload), "size 必须是非负整数")


def case_write_file_accepts_and_rejects():
    good = {
        "ok": True,
        "errors": [],
        "path": "a.txt",
        "size": 3,
        "mtime_ns": 1795689807077378000,
    }
    check(check_write_file(good) == good, "write_file 合法载荷应通过")

    payload = copy.deepcopy(good)
    payload["size"] = True
    expect_raises(
        ContractError, lambda: check_write_file(payload), "size 必须是非负整数"
    )

    payload = copy.deepcopy(good)
    payload["mtime_ns"] = True
    expect_raises(
        ContractError, lambda: check_write_file(payload), "mtime_ns 必须是整数"
    )

    payload = copy.deepcopy(good)
    del payload["mtime_ns"]
    expect_raises(
        ContractError, lambda: check_write_file(payload), "mtime_ns 必须是整数"
    )

    payload = copy.deepcopy(good)
    payload["mtime_ns"] = "1795689807077378000"
    expect_raises(
        ContractError, lambda: check_write_file(payload), "mtime_ns 必须是整数"
    )

    payload = copy.deepcopy(good)
    payload["path"] = ""
    expect_raises(ContractError, lambda: check_write_file(payload), "path 不能为空")

    payload = copy.deepcopy(good)
    payload["path"] = "../x"
    expect_raises(ContractError, lambda: check_write_file(payload), "不能包含 ..")


def case_stat_accepts_and_rejects():
    file_payload = {
        "ok": True,
        "errors": [],
        "path": "a.txt",
        "kind": "file",
        "size": 3,
        "mtime_ns": 1795689807077378000,
    }
    missing = {
        "ok": True,
        "errors": [],
        "path": "gone.txt",
        "kind": "missing",
        "size": None,
        "mtime_ns": None,
    }
    directory = {
        "ok": True,
        "errors": [],
        "path": "sub",
        "kind": "dir",
        "size": None,
        "mtime_ns": None,
    }
    check(check_stat(file_payload) == file_payload, "stat file 载荷应通过")
    check(check_stat(missing) == missing, "stat missing 载荷应通过")
    check(check_stat(directory) == directory, "stat dir 载荷应通过")

    payload = copy.deepcopy(file_payload)
    payload["kind"] = "weird"
    expect_raises(
        ContractError, lambda: check_stat(payload), "kind 只能是 file / missing / dir"
    )

    payload = copy.deepcopy(file_payload)
    payload["size"] = True
    expect_raises(ContractError, lambda: check_stat(payload), "size 必须是非负整数")

    payload = copy.deepcopy(file_payload)
    payload["mtime_ns"] = True
    expect_raises(ContractError, lambda: check_stat(payload), "mtime_ns 必须是整数")

    payload = copy.deepcopy(file_payload)
    del payload["mtime_ns"]
    expect_raises(ContractError, lambda: check_stat(payload), "mtime_ns 必须是整数")

    payload = copy.deepcopy(missing)
    payload["size"] = 0
    expect_raises(
        ContractError, lambda: check_stat(payload), "不是 file 时 size 必须是 null"
    )

    payload = copy.deepcopy(directory)
    payload["mtime_ns"] = 1
    expect_raises(
        ContractError, lambda: check_stat(payload), "不是 file 时 mtime_ns 必须是 null"
    )

    failed = {"ok": False, "errors": ["不是文件：nope"], "path": "nope"}
    check(check_stat(failed) == failed, "stat 失败载荷应通过")


def case_path_result_accepts_and_rejects():
    done = {"ok": True, "errors": [], "path": "newdir"}
    check(check_path_result(done, "mkdir") == done, "path_result 成功载荷应通过")

    failed = {"ok": False, "errors": ["已存在：newdir"], "path": "newdir"}
    check(check_path_result(failed, "mkdir") == failed, "path_result 失败载荷应通过")

    payload = {"ok": True, "errors": []}
    expect_raises(
        ContractError, lambda: check_path_result(payload, "mkdir"), "path 必须是字符串"
    )

    payload = {"ok": True, "errors": [], "path": "../x"}
    expect_raises(
        ContractError, lambda: check_path_result(payload, "mkdir"), "不能包含 .."
    )


CASES = [
    ("check_health 拒绝畸形载荷", case_health_rejects),
    ("check_plugins 拒绝畸形载荷", case_plugins_rejects),
    ("check_validate 拒绝畸形载荷", case_validate_rejects),
    ("check_validate 接受正常载荷", case_validate_accepts),
    ("check_run 拒绝畸形载荷", case_run_rejects),
    ("check_run 接受正常载荷", case_run_accepts),
    ("check_project 接受合法/拒绝畸形", case_project_accepts_and_rejects),
    ("check_tree 接受合法/拒绝畸形", case_tree_accepts_and_rejects),
    ("check_file 接受合法/拒绝畸形", case_file_accepts_and_rejects),
    ("check_write_file 接受合法/拒绝畸形", case_write_file_accepts_and_rejects),
    ("check_stat 接受合法/拒绝畸形", case_stat_accepts_and_rejects),
    ("check_path_result 接受合法/拒绝畸形", case_path_result_accepts_and_rejects),
    ("真实服务四个响应通过对应校验器", case_real_service_payloads),
]


def main():
    return run_cases("contract", CASES)


if __name__ == "__main__":
    sys.exit(main())
