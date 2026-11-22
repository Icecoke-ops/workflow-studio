"""engine.hooks 执行钩子测试（契约：docs/CONTRACT.md 第 9 节）。

只按契约写，不按当前实现写：契约与实现不一致时按契约断言，失败项在汇报里单列。
直接运行：python tests/test_hooks.py
"""

import gc
import importlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import types
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import hooks as hooks_mod
from engine.errors import (
    ExecutionError,
    HookError,
    MissingInput,
    RunAborted,
    ValidationFailed,
)
from engine.registry import Registry
from engine.runner import Execution, execute, run
from engine.workflow import validate

from _harness import check, env_guard, expect_raises, run_cases, write_zip

HOOK_EVENTS = [
    "plugins_loaded",
    "workflow_loaded",
    "env_ready",
    "node_create_before",
    "node_create_after",
    "node_invoke_before",
    "node_end",
    "run_end",
]

# 9.2 表：每个事件 data 的键（回读字段之外也包含只读字段）
EVENT_DATA_KEYS = {
    "plugins_loaded": ["components", "plugins", "types"],
    "workflow_loaded": ["path", "workflow"],
    "env_ready": ["env"],
    "node_create_before": ["config", "node"],
    "node_create_after": ["instance", "node"],
    "node_invoke_before": ["inputs", "node"],
    "node_end": ["duration_ms", "node", "outputs"],
    "run_end": ["duration_ms", "error", "order", "status"],
}

# 事件触发时 ctx.execution 还是 None 的那批（9.1：实例全部建好才填上）
BEFORE_EXECUTION_EVENTS = {
    "plugins_loaded",
    "workflow_loaded",
    "env_ready",
    "node_create_before",
    "node_create_after",
}


# ---------------------------------------------------------------------------
# 临时插件：Echo / Sink / TwoIn / Touch / Boom / ModelOut
# ---------------------------------------------------------------------------

_PLUGIN_SOURCE = '''\
from engine.api import Component, PredictorModel

PLUGIN_NAME = "hk1"
PLUGIN_VERSION = "1.0"
PLUGIN_TITLE = "钩子测试"


class Echo(Component):
    name = "Echo"
    title = "回声"
    CLOSED = []

    @staticmethod
    def config_schema():
        return {"tag": {"type": "string", "default": "d0"}}

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"value": {"type": "num"}}

    def __init__(self, config):
        self.tag = config["tag"]

    def invoke(self):
        return {"value": self.tag}

    def close(self):
        Echo.CLOSED.append(self.tag)


class Sink(Component):
    name = "Sink"
    title = "汇聚"
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
        return {"result": value + "!" if isinstance(value, str) else value * 2}


class TwoIn(Component):
    name = "TwoIn"
    title = "双输入"

    @staticmethod
    def config_schema():
        return {}

    @staticmethod
    def input_schema():
        return {
            "model": {"types": ["num"], "required": True},
            "data": {"types": ["num"], "required": True},
        }

    @staticmethod
    def output_schema():
        return {"out": {"type": "num"}}

    def __init__(self, config):
        pass

    def invoke(self, model, data):
        return {"out": [model, data]}


class Touch(Component):
    name = "Touch"
    title = "留痕"

    @staticmethod
    def config_schema():
        return {"path": {"type": "string", "required": True}}

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"value": {"type": "num"}}

    def __init__(self, config):
        self.path = config["path"]

    def invoke(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("ran")
        return {"value": 1}


class Boom(Component):
    name = "Boom"
    title = "爆炸"

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
        raise ValueError("故意失败")


class _GoodPredictor(PredictorModel):
    def predict(self, frame):
        return [0.0] * len(frame)


class ModelOut(Component):
    name = "ModelOut"
    title = "出模型"

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


COMPONENTS = [Echo, Sink, TwoIn, Touch, Boom, ModelOut]
'''

_TEMP_DIR = None
_REGISTRY = None


def get_registry():
    global _TEMP_DIR, _REGISTRY
    if _REGISTRY is None:
        _TEMP_DIR = tempfile.TemporaryDirectory(prefix="engine_hooks_test_")
        write_zip(
            _TEMP_DIR.name,
            "hk1.zip",
            {
                "hk1/__init__.py": "",
                "hk1/components.py": _PLUGIN_SOURCE,
                "hk1/types.py": 'TYPES = {"num": "数字"}\n',
            },
        )
        _REGISTRY = Registry().load(_TEMP_DIR.name)
    return _REGISTRY


def _release_zip(zip_str):
    """释放 zipimport 与 importlib 留下的句柄，否则 Windows 删不掉临时目录。"""
    while zip_str in sys.path:
        sys.path.remove(zip_str)
    for name in [n for n in sys.modules if n == "hk1" or n.startswith("hk1.")]:
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
        zip_str = str((Path(_TEMP_DIR.name) / "hk1.zip").resolve())
        _release_zip(zip_str)
        _TEMP_DIR.cleanup()
        _TEMP_DIR = None
    _REGISTRY = None


def component_class(name):
    entry = get_registry().get_component("hk1", name)
    check(entry is not None, f"组件 hk1.{name} 未注册")
    return entry.cls


# ---------------------------------------------------------------------------
# 夹具构造
# ---------------------------------------------------------------------------

_RECORDER_HOOK = '''\
import json
import os

_EVENTS = (
    "plugins_loaded", "workflow_loaded", "env_ready",
    "node_create_before", "node_create_after",
    "node_invoke_before", "node_end", "run_end",
)


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return {"__type__": type(value).__name__}


def install(ctx):
    log = os.environ["HK_LOG"]

    def record(event, data, execution):
        payload = {
            "event": event,
            "keys": sorted(data),
            "execution_is_none": execution is None,
            "data": _jsonable(data),
        }
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\\n")

    record("install", {}, None)
    for event in _EVENTS:
        def callback(data, execution, event=event):
            record(event, data, execution)
        ctx.on(event, callback)
'''


def _write_hook(tmp, body, name="hookmod.py"):
    path = Path(tmp) / name
    path.write_text(body, encoding="utf-8")
    return path


def _write_hook_dir(tmp, dirname, filename, body):
    directory = Path(tmp) / dirname
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(body, encoding="utf-8")
    return directory


def _marker_hook(marker):
    return (
        "import os\n\n\n"
        "def install(ctx):\n"
        "    with open(os.environ['HK_MARK'], 'w', encoding='utf-8') as handle:\n"
        f"        handle.write({marker!r})\n"
    )


def _read_records(path):
    file_path = Path(path)
    if not file_path.is_file():
        return []
    text = file_path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _events(records):
    return [record["event"] for record in records]


def _echo(node_id="n1", tag="v1"):
    return {
        "id": node_id,
        "plugin": "hk1",
        "component": "Echo",
        "config": {"tag": tag},
        "inputs": {},
    }


def _sink(node_id, source, source_port="value", port="value"):
    return {
        "id": node_id,
        "plugin": "hk1",
        "component": "Sink",
        "config": {},
        "inputs": {port: {"from": source, "port": source_port}},
    }


def _write_workflow(tmp, nodes, *, name="hook_case", env=None):
    raw = {"name": name, "nodes": nodes}
    if env is not None:
        raw["env"] = env
    path = Path(tmp) / "workflow.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return path


def _validated(raw):
    report = validate(get_registry(), raw)
    check(report.ok, f"夹具工作流应校验通过：{report.errors}")
    return report.workflow


def _run_cli(args, tmp):
    """子进程跑 CLI；输出落文件（沙箱里管道不可用，沿用 test_ml 的做法）。"""
    log_path = Path(tmp) / "cli.log"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    env["PYTHONIOENCODING"] = "utf-8"
    with open(log_path, "wb") as handle:
        completed = subprocess.run(
            [sys.executable, "-m", "engine", *args],
            cwd=str(ROOT),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    return completed.returncode, log_path.read_text(encoding="utf-8", errors="replace")


def _run_with_recorder(tmp, nodes, *, hook_body=_RECORDER_HOOK, env=None, cli_env=None):
    """写工作流 + 记录钩子并 execute，返回 (execution, records)。"""
    log = Path(tmp) / "events.jsonl"
    os.environ["HK_LOG"] = str(log)
    hook = _write_hook(tmp, hook_body)
    path = _write_workflow(tmp, nodes, env=env)
    execution = execute(get_registry(), str(path), cli_env=cli_env, hook=str(hook))
    return execution, _read_records(log)


# ---------------------------------------------------------------------------
# 事件：顺序、data、execution 参数、注册与加载
# ---------------------------------------------------------------------------


def case_event_order():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_order_") as tmp, env_guard():
        execution, records = _run_with_recorder(
            tmp, [_echo("n1", "v1"), _sink("n2", "n1")]
        )
        check(
            records[0]["event"] == "install",
            f"install 应在 plugins_loaded 之前调用：{records[0]}",
        )
        sequence = [
            (record["event"], record["data"].get("node")) for record in records[1:]
        ]
        # 9.3：构造 Execution 时建全部实例，所以 create 事件先全部发生，再逐节点 invoke。
        expected = [
            ("plugins_loaded", None),
            ("workflow_loaded", None),
            ("env_ready", None),
            ("node_create_before", "n1"),
            ("node_create_after", "n1"),
            ("node_create_before", "n2"),
            ("node_create_after", "n2"),
            ("node_invoke_before", "n1"),
            ("node_end", "n1"),
            ("node_invoke_before", "n2"),
            ("node_end", "n2"),
            ("run_end", None),
        ]
        check(sequence == expected, f"事件顺序不符合契约 9.2/9.3：{sequence}")
        for record in records[1:]:
            is_before = record["event"] in BEFORE_EXECUTION_EVENTS
            check(
                record["execution_is_none"] is is_before,
                f"{record['event']} 的 execution 参数应是 "
                f"{'None' if is_before else 'Execution'}：{record['execution_is_none']}",
            )
        check(execution.order == ["n1", "n2"], f"执行顺序：{execution.order}")
        check(
            execution.status == {"n1": "fresh", "n2": "fresh"},
            f"跑完状态应全 fresh：{execution.status}",
        )


def case_event_data_keys():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_keys_") as tmp, env_guard():
        execution, records = _run_with_recorder(
            tmp, [_echo("n1", "v1"), _sink("n2", "n1")]
        )
        registry = get_registry()
        by_event = {}
        for record in records[1:]:
            by_event.setdefault(record["event"], []).append(record)
            check(
                record["keys"] == EVENT_DATA_KEYS[record["event"]],
                f"{record['event']} 的 data 键应为 "
                f"{EVENT_DATA_KEYS[record['event']]}，实际 {record['keys']}",
            )

        loaded = by_event["plugins_loaded"][0]["data"]
        check(
            set(loaded["plugins"]) >= {"std", "hk1"},
            f"plugins 应列出已加载插件：{loaded['plugins']}",
        )
        check(
            loaded["components"] == len(registry.components),
            f"components 应为注册组件数：{loaded['components']} != {len(registry.components)}",
        )
        check(
            loaded["types"] == len(registry.types),
            f"types 应为注册类型数：{loaded['types']} != {len(registry.types)}",
        )

        wf_record = by_event["workflow_loaded"][0]["data"]
        check(
            wf_record["workflow"]["name"] == "hook_case",
            f"workflow_loaded 应带原始 JSON：{wf_record['workflow']}",
        )
        check(
            wf_record["path"].endswith("workflow.json"),
            f"workflow_loaded 的 path：{wf_record['path']}",
        )

        create_before = {
            record["data"]["node"]: record["data"]["config"]
            for record in by_event["node_create_before"]
        }
        check(
            create_before["n1"] == {"tag": "v1"},
            f"node_create_before 应带已补默认值的 config：{create_before['n1']}",
        )
        create_after = {
            record["data"]["node"]: record["data"]["instance"]
            for record in by_event["node_create_after"]
        }
        check(
            create_after["n1"] == {"__type__": "Echo"}
            and create_after["n2"] == {"__type__": "Sink"},
            f"node_create_after 应带实例：{create_after}",
        )

        invoke = {record["data"]["node"]: record["data"]["inputs"]
                  for record in by_event["node_invoke_before"]}
        check(invoke["n1"] == {}, f"n1 没有输入：{invoke['n1']}")
        check(invoke["n2"] == {"value": "v1"}, f"n2 的输入应是上游输出：{invoke['n2']}")

        ends = {record["data"]["node"]: record["data"] for record in by_event["node_end"]}
        check(
            ends["n1"]["outputs"] == {"value": "v1"},
            f"node_end 应带输出：{ends['n1']['outputs']}",
        )
        check(
            isinstance(ends["n1"]["duration_ms"], (int, float))
            and ends["n1"]["duration_ms"] >= 0,
            f"node_end 的 duration_ms 应是非负数：{ends['n1']['duration_ms']}",
        )

        run_end = by_event["run_end"][0]["data"]
        check(run_end["status"] == "ok", f"run_end.status：{run_end['status']}")
        check(run_end["order"] == ["n1", "n2"], f"run_end.order：{run_end['order']}")
        check(run_end["error"] is None, f"成功运行 error 应为 None：{run_end['error']}")
        check(
            isinstance(run_end["duration_ms"], (int, float))
            and run_end["duration_ms"] >= 0,
            f"run_end.duration_ms：{run_end['duration_ms']}",
        )
        check(
            len(by_event["run_end"]) == 1,
            f"run_end 应只触发一次：{len(by_event['run_end'])}",
        )
        check(execution.status == {"n1": "fresh", "n2": "fresh"}, "运行应成功")


def case_unknown_event_name():
    context = hooks_mod.HookContext()
    exc = expect_raises(
        HookError,
        lambda: context.on("node_done", lambda data, execution: None),
        "未知事件名",
        "node_done",
    )
    for event in HOOK_EVENTS:
        check(event in str(exc), f"错误信息应列出合法事件 {event}：{exc}")
    with tempfile.TemporaryDirectory(prefix="engine_hooks_unknown_") as tmp:
        hook = _write_hook(
            tmp,
            "def install(ctx):\n"
            "    ctx.on('node_done', lambda data, execution: None)\n",
        )
        expect_raises(HookError, lambda: hooks_mod.load(hook), "未知事件名")


def case_hook_path_resolution():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_path_") as tmp, env_guard():
        mark = Path(tmp) / "mark.txt"
        os.environ["HK_MARK"] = str(mark)

        both = _write_hook_dir(tmp, "both", "hook.py", _marker_hook("hook.py"))
        _write_hook_dir(tmp, "both", "__init__.py", _marker_hook("__init__.py"))
        hooks_mod.load(both)
        check(
            mark.read_text(encoding="utf-8") == "hook.py",
            "目录里同时有 hook.py 和 __init__.py 时应优先 hook.py",
        )

        initonly = _write_hook_dir(
            tmp, "initonly", "__init__.py", _marker_hook("__init__.py")
        )
        hooks_mod.load(initonly)
        check(
            mark.read_text(encoding="utf-8") == "__init__.py",
            "只有 __init__.py 时应加载它",
        )

        direct = _write_hook(tmp, _marker_hook("direct"), name="direct_hook.py")
        hooks_mod.load(direct)
        check(mark.read_text(encoding="utf-8") == "direct", "文件路径应直接加载")

        empty = Path(tmp) / "empty"
        empty.mkdir()
        exc = expect_raises(HookError, lambda: hooks_mod.load(empty))
        check("hook.py" in str(exc) and "__init__.py" in str(exc), f"缺文件提示：{exc}")

        missing = Path(tmp) / "no_such_hook"
        expect_raises(HookError, lambda: hooks_mod.load(missing), "不存在")

        noinstall = _write_hook(tmp, "X = 1\n", name="noinstall.py")
        expect_raises(HookError, lambda: hooks_mod.load(noinstall), "install")


def case_duplicate_hook():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_dup_") as tmp:
        get_registry()
        hook_a = _write_hook(tmp, "def install(ctx):\n    pass\n", "a.py")
        hook_b = _write_hook(tmp, "def install(ctx):\n    pass\n", "b.py")
        wf = _write_workflow(tmp, [_echo()])
        code, out = _run_cli(
            ["--hook", str(hook_a), "--hook", str(hook_b), "run", str(wf)], tmp
        )
        check(code != 0, f"重复 --hook 应失败，实际 exit {code}：{out}")
        check("只能指定一个" in out, f"错误信息应说明只能一个：{out}")


# ---------------------------------------------------------------------------
# 五个采信点：改了生效 + 改别的字段被忽略
# ---------------------------------------------------------------------------

_WORKFLOW_MUTATE_HOOK = '''\
def install(ctx):
    def on_loaded(data, execution):
        for node in data["workflow"]["nodes"]:
            if node["id"] == "n1":
                node["config"]["tag"] = "changed"
        data["path"] = "hacked"
        data["extra"] = 1
    ctx.on("workflow_loaded", on_loaded)
'''

_WORKFLOW_INVALID_HOOK = '''\
def install(ctx):
    def on_loaded(data, execution):
        for node in data["workflow"]["nodes"]:
            if node["id"] == "n1":
                node["config"]["tag"] = 123
    ctx.on("workflow_loaded", on_loaded)
'''


def case_workflow_loaded_applies():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_wf_") as tmp, env_guard():
        sink = component_class("Sink")
        sink.RECEIVED.clear()
        execution, _ = _run_with_recorder(
            tmp,
            [_echo("n1", "v1"), _sink("n2", "n1")],
            hook_body=_WORKFLOW_MUTATE_HOOK,
        )
        check(
            execution.results["n1"].outputs == {"value": "changed"},
            f"执行应使用钩子改后的 config：{execution.results['n1'].outputs}",
        )
        check(
            sink.RECEIVED == ["changed"],
            f"下游应收到改后的值：{sink.RECEIVED}",
        )
        check(execution.order == ["n1", "n2"], f"改其它键不应影响节点：{execution.order}")


def case_workflow_loaded_invalid_aborts():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_wf_bad_") as tmp, env_guard():
        sink = component_class("Sink")
        echo = component_class("Echo")
        sink.RECEIVED.clear()
        echo.CLOSED.clear()
        os.environ["HK_LOG"] = str(Path(tmp) / "events.jsonl")
        hook = _write_hook(tmp, _WORKFLOW_INVALID_HOOK)
        wf = _write_workflow(tmp, [_echo("n1", "v1"), _sink("n2", "n1")])
        exc = expect_raises(
            ValidationFailed,
            lambda: execute(get_registry(), str(wf), hook=str(hook)),
        )
        check(
            any("tag" in error for error in exc.report.errors),
            f"改坏的 config 应重新校验并报错：{exc.report.errors}",
        )
        check(sink.RECEIVED == [], "校验失败时不能开跑")
        check(echo.CLOSED == [], "校验失败时不应建实例")


_ENV_HOOK = '''\
import json
import os


def install(ctx):
    def on_env(data, execution):
        with open(os.environ["HK_LOG"], "w", encoding="utf-8") as handle:
            json.dump(
                {"env": dict(data["env"]), "execution_is_none": execution is None},
                handle,
                ensure_ascii=False,
            )
        data["env"]["HK_A"] = "9"
        data["env"]["HK_C"] = "3"
    ctx.on("env_ready", on_env)
'''


def case_env_ready_applies():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_env_") as tmp, env_guard():
        for key in ("HK_A", "HK_B", "HK_C"):
            os.environ.pop(key, None)
        os.environ["HK_KEEP"] = "keep"
        log = Path(tmp) / "env.json"
        os.environ["HK_LOG"] = str(log)
        hook = _write_hook(tmp, _ENV_HOOK)
        wf = _write_workflow(tmp, [_echo()], env={"HK_A": "1"})
        execute(get_registry(), str(wf), cli_env={"HK_B": "2"}, hook=str(hook))
        recorded = json.loads(log.read_text(encoding="utf-8"))
        check(
            recorded["env"] == {"HK_A": "1", "HK_B": "2"},
            f"env_ready 的 env 应是工作流 env + -e 的合并（不含自动注入）：{recorded['env']}",
        )
        check(recorded["execution_is_none"] is True, "env_ready 时 execution 应是 None")
        check(os.environ["HK_A"] == "9", f"钩子改的 env 应写回：{os.environ.get('HK_A')}")
        check(os.environ["HK_C"] == "3", f"钩子新增的 env 应写回：{os.environ.get('HK_C')}")
        check(
            os.environ["HK_B"] == "2",
            "钩子没动的键不能被删除（只覆盖不删除）",
        )
        check(
            os.environ["HK_KEEP"] == "keep",
            "钩子 env 里没出现的既有变量不能被删除",
        )


_CREATE_HOOK = '''\
def install(ctx):
    def on_create(data, execution):
        if data["node"] == "n1":
            data["config"]["tag"] = "rebuilt"
        data["node"] = "ghost"
        data["extra"] = True
    ctx.on("node_create_before", on_create)
'''


def case_node_create_before_applies():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_create_") as tmp, env_guard():
        sink = component_class("Sink")
        sink.RECEIVED.clear()
        execution, _ = _run_with_recorder(
            tmp,
            [_echo("n1", "v1"), _sink("n2", "n1")],
            hook_body=_CREATE_HOOK,
        )
        check(
            execution.results["n1"].outputs == {"value": "rebuilt"},
            f"重建的实例应拿到新 config：{execution.results['n1'].outputs}",
        )
        check(sink.RECEIVED == ["rebuilt"], f"下游应收到新 config 的结果：{sink.RECEIVED}")
        check(
            execution.order == ["n1", "n2"],
            f"改 node 等其它键应被忽略：{execution.order}",
        )


_INVOKE_HOOK = '''\
def install(ctx):
    def on_invoke(data, execution):
        if data["node"] == "n2":
            data["inputs"]["value"] = 99
        data["node"] = "ghost"
    ctx.on("node_invoke_before", on_invoke)
'''


def case_node_invoke_before_applies():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_invoke_") as tmp, env_guard():
        sink = component_class("Sink")
        sink.RECEIVED.clear()
        execution, _ = _run_with_recorder(
            tmp,
            [_echo("n1", "v1"), _sink("n2", "n1")],
            hook_body=_INVOKE_HOOK,
        )
        check(sink.RECEIVED == [99], f"invoke 应收到钩子改的 inputs：{sink.RECEIVED}")
        check(
            execution.results["n2"].outputs == {"result": 198},
            f"下游输出：{execution.results['n2'].outputs}",
        )
        check(execution.order == ["n1", "n2"], "改 node 等其它键应被忽略")


_INVOKE_EXTRA_HOOK = '''\
def install(ctx):
    def on_invoke(data, execution):
        if data["node"] == "n2":
            data["inputs"]["bogus"] = 1
    ctx.on("node_invoke_before", on_invoke)
'''

_INVOKE_MISSING_HOOK = '''\
def install(ctx):
    def on_invoke(data, execution):
        if data["node"] == "n2":
            data["inputs"].pop("value", None)
    ctx.on("node_invoke_before", on_invoke)
'''


def case_node_invoke_before_key_mismatch():
    for body in (_INVOKE_EXTRA_HOOK, _INVOKE_MISSING_HOOK):
        with tempfile.TemporaryDirectory(prefix="engine_hooks_keys_") as tmp, env_guard():
            hook = _write_hook(tmp, body)
            wf = _write_workflow(tmp, [_echo("n1", "v1"), _sink("n2", "n1")])
            expect_raises(
                ExecutionError,
                lambda: execute(get_registry(), str(wf), hook=str(hook)),
                "输入端口不匹配",
            )


_NODE_END_HOOK = '''\
def install(ctx):
    def on_end(data, execution):
        if data["node"] == "n1":
            data["outputs"]["value"] = 7
        data["node"] = "ghost"
        data["duration_ms"] = 999999.0
    ctx.on("node_end", on_end)
'''

_NODE_END_BAD_PORT_HOOK = '''\
def install(ctx):
    def on_end(data, execution):
        data["outputs"] = {"bogus": 1}
    ctx.on("node_end", on_end)
'''

_NODE_END_BAD_TYPE_HOOK = '''\
def install(ctx):
    def on_end(data, execution):
        data["outputs"]["model"] = object()
    ctx.on("node_end", on_end)
'''


def case_node_end_applies():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_end_") as tmp, env_guard():
        sink = component_class("Sink")
        sink.RECEIVED.clear()
        execution, _ = _run_with_recorder(
            tmp,
            [_echo("n1", "v1"), _sink("n2", "n1")],
            hook_body=_NODE_END_HOOK,
        )
        check(
            execution.results["n1"].outputs == {"value": 7},
            f"node_end 改后的输出应生效：{execution.results['n1'].outputs}",
        )
        check(sink.RECEIVED == [7], f"下游应收到改后的输出：{sink.RECEIVED}")
        heap = getattr(execution, "values", None)
        check(
            heap is not None,
            "契约 9.3：Execution 应暴露 values（(节点 id, 端口) -> 真实对象）",
        )
        check(
            heap.get(("n1", "value")) == 7,
            f"写进堆的应是钩子改后的值：{heap.get(('n1', 'value'))}",
        )
        check(execution.order == ["n1", "n2"], "改 node 等其它键应被忽略")


def case_node_end_invalid():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_end_bad_") as tmp, env_guard():
        hook = _write_hook(tmp, _NODE_END_BAD_PORT_HOOK)
        wf = _write_workflow(tmp, [_echo("n1", "v1")])
        expect_raises(
            ExecutionError,
            lambda: execute(get_registry(), str(wf), hook=str(hook)),
            "返回端口不匹配",
        )

        hook = _write_hook(tmp, _NODE_END_BAD_TYPE_HOOK, name="bad_type.py")
        wf = _write_workflow(
            tmp,
            [{"id": "n1", "plugin": "hk1", "component": "ModelOut",
              "config": {}, "inputs": {}}],
            name="model_case",
        )
        expect_raises(
            ExecutionError,
            lambda: execute(get_registry(), str(wf), hook=str(hook)),
            "没有继承 PredictorModel",
        )


# ---------------------------------------------------------------------------
# 执行语义
# ---------------------------------------------------------------------------

_RAISE_HOOK = '''\
import json
import os


def install(ctx):
    def on_invoke(data, execution):
        raise ValueError("钩子故意失败")

    def on_end(data, execution):
        with open(os.environ["HK_LOG"], "a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                {"status": data["status"], "error": data["error"]},
                ensure_ascii=False,
            ) + "\\n")

    ctx.on("node_invoke_before", on_invoke)
    ctx.on("run_end", on_end)
'''


def case_callback_exception_aborts():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_raise_") as tmp, env_guard():
        echo = component_class("Echo")
        echo.CLOSED.clear()
        log = Path(tmp) / "run_end.jsonl"
        os.environ["HK_LOG"] = str(log)
        hook = _write_hook(tmp, _RAISE_HOOK)
        wf = _write_workflow(tmp, [_echo("n1", "v1")])
        exc = expect_raises(
            RunAborted,
            lambda: execute(get_registry(), str(wf), hook=str(hook)),
            "钩子故意失败",
        )
        check(
            isinstance(exc.__cause__, ValueError),
            f"RunAborted.__cause__ 应是原异常，实际 {type(exc.__cause__).__name__}",
        )
        check(
            str(exc.__cause__) == "钩子故意失败",
            f"__cause__ 应是原异常：{exc.__cause__}",
        )
        records = _read_records(log)
        check(len(records) == 1, f"run_end 仍应触发一次：{records}")
        check(records[0]["status"] == "failed", f"run_end.status：{records[0]['status']}")
        check(
            "钩子故意失败" in (records[0]["error"] or ""),
            f"run_end.error 应带原因：{records[0]['error']}",
        )
        check(echo.CLOSED == ["v1"], f"中止后实例应被 close：{echo.CLOSED}")


def case_missing_input_text():
    raw = {
        "name": "missing",
        "nodes": [
            _echo("n1", "a"),
            _echo("n5", "b"),
            {
                "id": "n3",
                "plugin": "hk1",
                "component": "TwoIn",
                "config": {},
                "inputs": {
                    "model": {"from": "n5", "port": "value"},
                    "data": {"from": "n1", "port": "value"},
                },
            },
        ],
    }
    execution = Execution(_validated(raw), get_registry())
    try:
        execution.run_node("n1")
        try:
            execution.run_node("n3")
        except MissingInput as exc:
            actual = str(exc)
        else:
            raise AssertionError("缺输入时应抛 MissingInput")
    finally:
        execution.close()
    expected = (
        "节点 n3（hk1.TwoIn）缺少输入：\n"
        "  model  ← 来自 n5「回声」，该节点尚未执行\n"
        "  data   ← 来自 n1「回声」，已执行 ✓\n"
        "建议：先执行 n5"
    )
    check(
        actual == expected,
        f"缺输入文案应与契约 9.4 逐字一致：\n期望 {expected!r}\n实际 {actual!r}",
    )


def case_run_node_rebuild():
    echo = component_class("Echo")
    echo.CLOSED.clear()
    execution = Execution(_validated({"name": "rebuild", "nodes": [_echo("n1", "d0")]}),
                          get_registry())
    try:
        check(
            execution.run_node("n1").outputs == {"value": "d0"},
            "初始实例应拿到默认 config",
        )
        check(echo.CLOSED == [], "还没重建，不应 close 旧实例")
        check(
            execution.run_node("n1", {"tag": "new"}).outputs == {"value": "new"},
            "config 变了应按新 config 重建",
        )
        check(echo.CLOSED == ["d0"], f"旧实例应被 close：{echo.CLOSED}")
        execution.run_node("n1")
        execution.run_node("n1", {"tag": "new"})
        check(
            echo.CLOSED == ["d0"],
            f"config 没变时不应重建：{echo.CLOSED}",
        )
        check(
            execution.run_node("n1", {"tag": "d0"}).outputs == {"value": "d0"},
            "config 再变回应重建",
        )
        check(
            echo.CLOSED == ["d0", "new"],
            f"第二次重建前应 close 当前实例：{echo.CLOSED}",
        )
    finally:
        execution.close()


def case_stale_propagation():
    execution = Execution(
        _validated(
            {
                "name": "stale",
                "nodes": [
                    _echo("n1", "v"),
                    _sink("n2", "n1"),
                    _sink("n3", "n2", source_port="result"),
                    _sink("n4", "n3", source_port="result"),
                ],
            }
        ),
        get_registry(),
    )
    try:
        for node_id in ("n1", "n2", "n3"):
            execution.run_node(node_id)
        execution.run_node("n1")
        expected = {
            "n1": "fresh",
            "n2": "stale",
            "n3": "stale",
            "n4": "unrun",
        }
        check(
            execution.status == expected,
            f"下游 stale 应递归传播，unrun 保持 unrun：{execution.status}",
        )
    finally:
        execution.close()


def case_on_start():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_start_") as tmp, env_guard():
        log = Path(tmp) / "events.jsonl"
        os.environ["HK_LOG"] = str(log)
        hook = _write_hook(tmp, _RECORDER_HOOK)
        wf = _write_workflow(tmp, [_echo("n1", "v1")])
        calls = []

        def on_start(execution):
            # 状态要在回调当下快照，否则 execute 返回后 execution 已经跑完了。
            calls.append(
                (
                    execution,
                    list(_events(_read_records(log))),
                    dict(execution.status),
                )
            )

        try:
            execute(get_registry(), str(wf), hook=str(hook), on_start=on_start)
        except TypeError as exc:
            raise AssertionError(
                f"契约 9.3：execute 应接受 on_start 参数（校验后、建实例前触发），"
                f"实际调用失败：{exc}"
            ) from None
        check(len(calls) == 1, f"on_start 应只触发一次，实际 {len(calls)} 次")
        execution, events, statuses = calls[0]
        check(
            isinstance(execution, Execution),
            f"on_start 应拿到 Execution，实际 {type(execution).__name__}",
        )
        check(
            events == ["install", "plugins_loaded", "workflow_loaded", "env_ready"],
            f"on_start 应在校验通过后、建实例前触发，当时事件：{events}",
        )
        check(
            set(statuses.values()) == {"unrun"},
            f"on_start 时所有节点应还是 unrun：{statuses}",
        )


def case_zero_change_with_hook():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_zero_") as tmp, env_guard():
        raw = {"name": "zero", "nodes": [_echo("n1", "v1"), _sink("n2", "n1")]}
        workflow = _validated(raw)
        plain = run(workflow, get_registry())
        execution, _ = _run_with_recorder(tmp, raw["nodes"])
        with_hook = execution.results
        plain_values = {node_id: result.outputs for node_id, result in plain.items()}
        hook_values = {node_id: result.outputs for node_id, result in with_hook.items()}
        check(
            plain_values == hook_values,
            f"带 hook 与不带 hook 跑同一图，堆里的值应相同：{plain_values} vs {hook_values}",
        )


# ---------------------------------------------------------------------------
# 官方钩子 hooks/result_file/
# ---------------------------------------------------------------------------

RESULT_FILE_HOOK = str(ROOT / "hooks" / "result_file")


def case_result_file_success():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_result_") as tmp:
        get_registry()
        wf = _write_workflow(tmp, [_echo("n1", "v1"), _sink("n2", "n1")])
        result = Path(tmp) / "result.json"
        code, out = _run_cli(
            [
                "run",
                "--hook",
                RESULT_FILE_HOOK,
                "-e",
                f"hook_result_path={result}",
                "-p",
                _TEMP_DIR.name,
                str(wf),
            ],
            tmp,
        )
        check(code == 0, f"result_file 正常跑应 exit 0，实际 {code}：{out}")
        check(result.is_file(), f"应写出结果 JSON：{out}")
        payload = json.loads(result.read_text(encoding="utf-8"))
        check(
            set(payload) == {"status", "error", "order", "nodes"},
            f"9.5 顶层键：{sorted(payload)}",
        )
        check(payload["status"] == "ok", f"status：{payload['status']}")
        check(payload["error"] is None, f"error 应为 null：{payload['error']}")
        check(payload["order"] == ["n1", "n2"], f"order：{payload['order']}")
        check(set(payload["nodes"]) == {"n1", "n2"}, f"nodes：{sorted(payload['nodes'])}")
        for node_id, entry in payload["nodes"].items():
            check(
                set(entry) == {"duration_ms", "outputs"},
                f"{node_id} 的字段：{sorted(entry)}",
            )
            check(
                isinstance(entry["duration_ms"], (int, float))
                and entry["duration_ms"] >= 0,
                f"{node_id}.duration_ms：{entry['duration_ms']}",
            )
            check(isinstance(entry["outputs"], dict), f"{node_id}.outputs 应是对象")
            check(
                all(isinstance(value, str) for value in entry["outputs"].values()),
                f"{node_id}.outputs 应经 preview() 转成字符串：{entry['outputs']}",
            )


def case_result_file_missing_env():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_result_env_") as tmp:
        get_registry()
        marker = Path(tmp) / "ran.txt"
        wf = _write_workflow(
            tmp,
            [
                {
                    "id": "n1",
                    "plugin": "hk1",
                    "component": "Touch",
                    "config": {"path": str(marker)},
                    "inputs": {},
                }
            ],
        )
        code, out = _run_cli(
            ["run", "--hook", RESULT_FILE_HOOK, "-p", _TEMP_DIR.name, str(wf)], tmp
        )
        check(code != 0, f"没设 hook_result_path 应失败，实际 exit {code}：{out}")
        check("hook_result_path" in out, f"错误信息应指出缺哪个变量：{out}")
        check(not marker.exists(), "钩子 install 失败时不能开跑")


def case_result_file_failed():
    with tempfile.TemporaryDirectory(prefix="engine_hooks_result_fail_") as tmp:
        get_registry()
        wf = _write_workflow(
            tmp,
            [{"id": "n1", "plugin": "hk1", "component": "Boom",
              "config": {}, "inputs": {}}],
            name="boom_case",
        )
        result = Path(tmp) / "result.json"
        code, out = _run_cli(
            [
                "run",
                "--hook",
                RESULT_FILE_HOOK,
                "-e",
                f"hook_result_path={result}",
                "-p",
                _TEMP_DIR.name,
                str(wf),
            ],
            tmp,
        )
        check(code != 0, f"运行失败应 exit 非 0，实际 {code}：{out}")
        check(result.is_file(), f"运行失败也应写出结果 JSON：{out}")
        payload = json.loads(result.read_text(encoding="utf-8"))
        check(payload["status"] == "failed", f"status：{payload['status']}")
        check(payload["error"], f"失败运行 error 不能为空：{payload['error']}")
        check(payload["order"] == ["n1"], f"order：{payload['order']}")


# ---------------------------------------------------------------------------
# 官方钩子 hooks/http_debug/：accept 瞬态错误后服务仍存活（v0.5.1 回归）
# ---------------------------------------------------------------------------


def case_http_debug_survives_accept_error():
    """一次 accept OSError 之后服务仍活着并能应答；修复前会 break 退出。"""
    from hooks.http_debug import server as server_mod

    real = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    real.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    real.bind(("127.0.0.1", 0))
    real.listen()
    port = real.getsockname()[1]

    class FlakyListener:
        """包一层真实监听 socket：第一次 accept 抛 OSError，之后转发。"""

        def __init__(self, inner):
            self.inner = inner
            self.accept_calls = 0
            self.injected = threading.Event()

        def accept(self):
            self.accept_calls += 1
            if self.accept_calls == 1:
                self.injected.set()
                raise OSError(10054, "injected transient accept error")
            return self.inner.accept()

        def settimeout(self, value):
            return self.inner.settimeout(value)

        def getsockname(self):
            return self.inner.getsockname()

        def close(self):
            return self.inner.close()

    flaky = FlakyListener(real)
    original_socket = server_mod.socket
    server_mod.socket = types.SimpleNamespace(
        create_server=lambda addr: flaky,
        timeout=socket.timeout,
        MSG_PEEK=socket.MSG_PEEK,
    )
    server = None
    thread = None
    try:
        with tempfile.TemporaryDirectory(prefix="engine_hooks_accept_") as tmp:
            server = server_mod.Server(
                port,
                "tok",
                str(Path(tmp) / "hook_port"),
                lambda connection, message: None,
            )
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            check(flaky.injected.wait(5), "夹具没生效：第一次 accept 没有抛 OSError")
            check(thread.is_alive(), "一次 accept 错误后服务线程不应退出")

            response = b""
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
                    client.settimeout(5)
                    client.sendall(
                        b"POST /nope HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                        b"Content-Length: 0\r\n\r\n"
                    )
                    while b"\r\n\r\n" not in response:
                        chunk = client.recv(4096)
                        if not chunk:
                            break
                        response += chunk
            except OSError as exc:
                raise AssertionError(
                    f"accept 错误后服务不再接受连接（break 回归）：{exc}"
                ) from None
            check(
                response.startswith(b"HTTP/1.1 404"),
                f"应收到 HTTP 响应（不是空读/连接被拒），实际 {response!r}",
            )
            check(b"not found" in response, f"响应体应来自服务端：{response!r}")
            check(thread.is_alive(), "应答之后服务线程仍应活着")

            server._stop.set()
            thread.join(timeout=5)
            check(not thread.is_alive(), "stop 后服务线程应退出")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    still_open = True
            except OSError:
                still_open = False
            check(not still_open, "stop 后监听端口应关闭")
    finally:
        server_mod.socket = original_socket
        if server is not None:
            server._stop.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        real.close()


CASES = [
    ("事件顺序：前三个 → 建实例 → 逐节点执行 → run_end", case_event_order),
    ("每个事件的 data 键与 9.2 表一致", case_event_data_keys),
    ("未知事件名报错并列出 8 个合法名", case_unknown_event_name),
    ("钩子路径：hook.py 优先、__init__.py 兜底、缺文件/缺 install 报错", case_hook_path_resolution),
    ("重复 --hook 报错", case_duplicate_hook),
    ("workflow_loaded：改 config 生效且重新校验，改其它键无效", case_workflow_loaded_applies),
    ("workflow_loaded：改成非法值中止且不开跑", case_workflow_loaded_invalid_aborts),
    ("env_ready：改 env 生效且只覆盖不删除", case_env_ready_applies),
    ("node_create_before：新 config 重建实例，改其它键无效", case_node_create_before_applies),
    ("node_invoke_before：改 inputs 生效，改其它键无效", case_node_invoke_before_applies),
    ("node_invoke_before：键集缺/多都报错", case_node_invoke_before_key_mismatch),
    ("node_end：改 outputs 写进堆，改其它键无效", case_node_end_applies),
    ("node_end：端口名/类型改坏都报错", case_node_end_invalid),
    ("回调抛异常 → RunAborted 且 run_end 仍触发", case_callback_exception_aborts),
    ("MissingInput 文案与 9.4 逐字一致", case_missing_input_text),
    ("run_node(config)：变了才重建并 close 旧实例", case_run_node_rebuild),
    ("stale 递归传播，unrun 保持 unrun", case_stale_propagation),
    ("execute(on_start) 在校验后、建实例前触发一次", case_on_start),
    ("带 hook 与不带 hook 的堆值相同", case_zero_change_with_hook),
    ("result_file：成功运行的 JSON 形状符合 9.5", case_result_file_success),
    ("result_file：没设 hook_result_path 启动即失败且不开跑", case_result_file_missing_env),
    ("result_file：运行失败也写 JSON，status=failed", case_result_file_failed),
    ("http_debug：一次 accept 错误后服务仍存活并能应答", case_http_debug_survives_accept_error),
]


def main():
    try:
        return run_cases("hooks", CASES)
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
