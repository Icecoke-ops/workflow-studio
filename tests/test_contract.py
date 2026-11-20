"""studio.contract 四个校验器的契约测试。

直接运行：python tests/test_contract.py
"""

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.registry import Registry
from studio.contract import (
    ContractError,
    check_health,
    check_plugins,
    check_run,
    check_validate,
)
from studio.server import EngineService

from _harness import check, expect_raises, run_cases

DEMO = ROOT / "workflows" / "linreg_demo.json"


# --------------------------------------------------------------------------
# 载荷构造
# --------------------------------------------------------------------------

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
            "component": "linreg.FitLinearRegression",
            "ms": 1.5,
            "outputs": {},
            "error": None,
        }
    ]
    return payload


# --------------------------------------------------------------------------
# check_health
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# check_plugins
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# check_validate
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# check_run
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# 正向：真实服务返回的四个响应都能通过对应校验器
# --------------------------------------------------------------------------

def case_real_service_payloads():
    registry = Registry().load(ROOT / "plugins")
    service = EngineService(registry)

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
    broken["nodes"][3]["config"]["target"] = "nope"
    failed = service.run(broken)
    check(failed["ok"] is False, "坏列名应在执行期失败")
    check(check_run(failed) == failed, "run 失败响应未通过契约")


CASES = [
    ("check_health 拒绝畸形载荷", case_health_rejects),
    ("check_plugins 拒绝畸形载荷", case_plugins_rejects),
    ("check_validate 拒绝畸形载荷", case_validate_rejects),
    ("check_validate 接受正常载荷", case_validate_accepts),
    ("check_run 拒绝畸形载荷", case_run_rejects),
    ("check_run 接受正常载荷", case_run_accepts),
    ("真实服务四个响应通过对应校验器", case_real_service_payloads),
]


def main():
    return run_cases("contract", CASES)


if __name__ == "__main__":
    sys.exit(main())
