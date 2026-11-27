"""测试公共设施：断言、异常匹配、用例循环、进程/端口探针，以及临时插件夹具。

每个 test_*.py 只保留自己的用例，跑测循环统一走这里。
"""

import ctypes
import http.client
import json
import os
import re
import socket
import time
import traceback
import zipfile
from contextlib import contextmanager
from pathlib import Path

from engine.registry import Registry
from engine.runner import run
from engine.workflow import validate

RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")

_ROOT = Path(__file__).resolve().parent.parent
_REGISTRY = None

# 回归演示工作流：唯一被测试依赖的示例已迁成 tests/fixtures 夹具。
DEMO_WORKFLOW = _ROOT / "tests" / "fixtures" / "regression_demo.flow"


# ---- 进程 / 端口（launcher 与 studio 测试共用） -------------------------

def _winapi():
    """kernel32 签名；不设 restype 的话 64 位句柄会被截断。"""
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes = (ctypes.c_uint32, ctypes.c_uint32)
    api.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    api.Process32First.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    api.Process32First.restype = ctypes.c_int
    api.Process32Next.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    api.Process32Next.restype = ctypes.c_int
    api.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    api.OpenProcess.restype = ctypes.c_void_p
    api.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
    api.GetExitCodeProcess.restype = ctypes.c_int
    api.TerminateProcess.argtypes = (ctypes.c_void_p, ctypes.c_uint)
    api.CloseHandle.argtypes = (ctypes.c_void_p,)
    return api


def pid_alive(pid):
    """进程还在吗：Windows 用 GetExitCodeProcess，其余平台 os.kill(pid, 0)。"""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    api = _winapi()
    handle = api.OpenProcess(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not api.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259  # STILL_ACTIVE
    finally:
        api.CloseHandle(handle)


def kill_pid(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 9)
        except OSError:
            pass
        return
    api = _winapi()
    handle = api.OpenProcess(0x0001, 0, pid)  # PROCESS_TERMINATE
    if handle:
        api.TerminateProcess(handle, 1)
        api.CloseHandle(handle)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def port_open(port, timeout=0.3):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_until(predicate, timeout, interval=0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def wait_port_closed(port, timeout=5.0):
    return wait_until(lambda: not port_open(port), timeout)


def wait_pid_gone(pid, timeout=5.0):
    return wait_until(lambda: not pid_alive(pid), timeout)


def http_raw(port, method, path, headers=None, payload=None, timeout=10.0):
    """发一条可自定义 Host/Origin 的请求，返回 (状态码, 原始字节)。

    默认 Host 指向 127.0.0.1:<port>（回环守卫放行的形状），调用方按需覆盖。
    """
    body = b""
    merged = {"Host": f"127.0.0.1:{port}"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        merged["Content-Type"] = "application/json; charset=utf-8"
    merged.update(headers or {})
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for key, value in merged.items():
            connection.putheader(key, value)
        if body:
            connection.putheader("Content-Length", str(len(body)))
        connection.endheaders(body or None)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_char * 260),
    ]


def children_of(parent_pid):
    """父进程的直接子进程（Windows Toolhelp 快照；WMI 在沙箱里被禁）。"""
    if os.name != "nt":
        return []
    api = _winapi()
    snapshot = api.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        return []
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(entry)
    found = []
    try:
        ok = api.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            if entry.th32ParentProcessID == parent_pid:
                found.append(entry.th32ProcessID)
            ok = api.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        api.CloseHandle(snapshot)
    return found


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def get_registry():
    """真实插件注册表只加载一次。

    run_all 是在同一进程里 exec_module 所有测试文件，不是每个文件独立进程；
    缓存能成立的真实原因是「用到它的文件都排在 test_cli 之前」——test_cli 会
    重新 load 插件并 purge 模块，但那之后 registry 里保存的类对象仍然可用。
    新加的测试若要用这个缓存，仍放在 test_cli 前面；否则自己 Registry().load()。

    例外：pickle/joblib 按「模块名 + 类名」反查类，purge 后缓存的类就与
    sys.modules 里的不是同一个对象了（会报 Can't pickle ...: it's not the same
    object）。要序列化插件里的对象，自己 Registry().load() 拿一份新注册表。
    """
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = Registry().load(_ROOT / "plugins")
    return _REGISTRY


def node(node_id, plugin, component, config=None, inputs=None):
    return {
        "id": node_id,
        "plugin": plugin,
        "component": component,
        "config": {} if config is None else config,
        "inputs": {} if inputs is None else inputs,
    }


def run_workflow(registry, raw):
    report = validate(registry, raw)
    check(report.ok, f"工作流应校验通过，实际错误：{report.errors}")
    return run(report.workflow, registry)


def expect_raises(exc_type, fn, *fragments):
    try:
        fn()
    except exc_type as exc:
        text = str(exc)
        for fragment in fragments:
            check(fragment in text, f"异常信息缺少 {fragment!r}，实际：{text!r}")
        return exc
    except Exception as exc:
        raise AssertionError(
            f"期望 {exc_type.__name__}，实际 {type(exc).__name__}: {exc}"
        ) from None
    raise AssertionError(f"期望 {exc_type.__name__}，但没有抛异常")


@contextmanager
def env_guard():
    """CLI 的 run 和 -e 会直接写 os.environ 且自己不还原，
    同进程跑后续用例会读到上一轮的残值，所以这里整份快照并还原。"""
    saved = dict(os.environ)
    try:
        yield
    finally:
        for key in set(os.environ) - set(saved):
            os.environ.pop(key, None)
        for key, value in saved.items():
            if os.environ.get(key) != value:
                os.environ[key] = value


def run_cases(label, cases):
    failed = 0
    for name, fn in cases:
        try:
            fn()
        except AssertionError as exc:
            print(f"FAIL {name}: {exc}")
            failed += 1
        except Exception:
            print(f"FAIL {name}: 意外异常")
            traceback.print_exc()
            failed += 1
        else:
            print(f"ok   {name}")
    if failed:
        print(f"\n[FAIL] {label}：{failed}/{len(cases)} 个用例失败")
        return 1
    print(f"\nOK  {label}：{len(cases)} 个用例全部通过")
    return 0


def invoke(registry, plugin, name, config=None, **inputs):
    """按引擎的方式补默认值再实例化后执行。

    直接调组件时必须先补默认值，否则要么 KeyError，要么测试自己手抄一份默认值、
    改产品默认值时悄无声息地脱节。
    """
    from engine.schema import fill_defaults

    entry = registry.get_component(plugin, name)
    if entry is None:
        raise AssertionError(f"组件不存在：{plugin}.{name}")
    instance = entry.cls(fill_defaults(entry.config_schema, config or {}))
    try:
        return instance.invoke(**inputs)
    finally:
        instance.close()


def write_demo_data(directory, filename="data.csv"):
    """regression_demo 的输入数据：y = 2x + 1 + 0.5*N(0,1)，200 行，R² 约 0.99。

    别用 3 行的迷你 CSV：20% 的测试集只剩 1 行，sklearn 的 r2 会打
    UndefinedMetricWarning 到 stderr，CLI 用例会因此误判「有错误输出」。
    """
    import numpy as np

    rng = np.random.default_rng(42)
    x = rng.uniform(0.0, 10.0, 200)
    y = 2.0 * x + 1.0 + rng.normal(0.0, 0.5, 200)
    lines = ["x,y"] + [f"{a},{b}" for a, b in zip(x, y)]
    path = Path(directory) / filename
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def source_node(directory, node_id="n1", filename="data.csv"):
    """table 类工作流的源头：写一个临时 CSV 并返回 ``fileio.LoadCSV`` 节点。

    插件层没有「造数据」组件了，要真正 run 的用例都得先落一个文件；路径用绝对路径，
    调用方就不用再为每个用例折腾 ``${workspace}``。
    """
    path = Path(directory) / filename
    path.write_text("x,y\n0,1\n1,3\n2,5\n", encoding="utf-8")
    return {
        "id": node_id,
        "plugin": "fileio",
        "component": "LoadCSV",
        "config": {"path": str(path)},
        "inputs": {},
    }


def write_plugin(root, package, entries):
    """把 {插件目录内相对路径: 文本} 写成 root/<package>/ 目录插件，返回插件目录。

    entries 的键相对插件目录（``components.py``、``impl/thing.py``…），
    契约见 docs/CONTRACT.md §2.1。
    """
    base = Path(root) / package
    for rel, content in entries.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return base


def write_zip(directory, filename, entries):
    """打一个插件 zip 文件：只给「插件根下的文件不参与扫描」的夹具用。"""
    path = Path(directory) / filename
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def component_source(
    class_name,
    input_schema="{}",
    output_schema="{}",
    attrs="",
    component_name=None,
    config_body="return {}",
    invoke_body="return {}",
    with_invoke=True,
    init_body="pass",
):
    lines = [
        f"class {class_name}(Component):",
        f'    name = "{component_name or class_name}"',
    ]
    if attrs:
        lines.extend(attrs.rstrip("\n").splitlines())
    lines.extend(
        [
            "",
            "    @staticmethod",
            "    def config_schema():",
            f"        {config_body}",
            "",
            "    @staticmethod",
            "    def input_schema():",
            f"        return {input_schema}",
            "",
            "    @staticmethod",
            "    def output_schema():",
            f"        return {output_schema}",
            "",
            "    def __init__(self, config):",
            f"        {init_body}",
        ]
    )
    if with_invoke:
        lines.extend(["", "    def invoke(self):", f"        {invoke_body}"])
    return "\n".join(lines)


def plugin_source(
    name,
    *,
    version="1.0",
    title="测试插件",
    class_name="Thing",
    input_schema="{}",
    output_schema="{}",
    extra="",
    attrs="",
    component=None,
    components=None,
    config_body="return {}",
    invoke_body="return {}",
    with_invoke=True,
    init_body="pass",
):
    """十几段临时插件源码只差元数据和端口 schema，收成一个模板，改加载器契约只改一处。"""
    if component is None:
        component = component_source(
            class_name,
            input_schema,
            output_schema,
            attrs,
            config_body=config_body,
            invoke_body=invoke_body,
            with_invoke=with_invoke,
            init_body=init_body,
        )
    if components is None:
        components = f"COMPONENTS = [{class_name}]"
    lines = []
    if extra:
        lines.extend(extra.rstrip("\n").splitlines())
    lines.extend(
        [
            "from engine.api import Component",
            "",
            f'PLUGIN_NAME = "{name}"',
            f'PLUGIN_VERSION = "{version}"',
            f'PLUGIN_TITLE = "{title}"',
        ]
    )
    lines.extend(["", component.rstrip("\n"), "", components])
    return "\n".join(lines) + "\n"
