"""P2 自检：同一进程里起 StudioServer，用 urllib 打五个接口并断言。

    python tests/test_studio_api.py

插件临时打到系统临时目录，跑完清理，不往仓库里丢东西。
"""

import csv
import ctypes
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import __version__ as ENGINE_VERSION  # noqa: E402
from engine.loader import DEFAULT_DIR  # noqa: E402
from engine.registry import Registry  # noqa: E402
from studio import debug as debug_module  # noqa: E402
from studio import server as server_module  # noqa: E402
from studio.contract import (  # noqa: E402
    ApiService,
    check_debug_start,
    check_debug_stop,
    check_health,
    check_plugins,
    check_run,
    check_validate,
)
from studio.debug import DebugManager  # noqa: E402
from studio.project import Project  # noqa: E402
from studio.server import EngineService, StudioServer  # noqa: E402
from websockets.sync.client import connect as ws_connect  # noqa: E402

DEMO = ROOT / "workflows" / "regression_demo.json"
DEBUG_DIR = Path(tempfile.gettempdir()) / "workflow-studio"


def debug_path(session, suffix):
    return DEBUG_DIR / f"debug_{session}.{suffix}"


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[OK] {message}")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_health(base, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=1) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            time.sleep(0.1)
    return None


def port_open(port, timeout=0.3):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_port_closed(port, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not port_open(port):
            return True
        time.sleep(0.1)
    return False


def pid_alive(pid):
    """进程还在吗：Windows 用 OpenProcess 探测，其余平台 os.kill(pid, 0)。"""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    api = _winapi()
    handle = api.OpenProcess(0x00100000, 0, pid)  # SYNCHRONIZE
    if not handle:
        return False
    api.CloseHandle(handle)
    return True


def wait_pid_gone(pid, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return not pid_alive(pid)


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
    api.CloseHandle.argtypes = (ctypes.c_void_p,)
    return api


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


class Api:
    """最小 HTTP 客户端：返回 (状态码, Content-Type, 原始文本)。"""

    def __init__(self, base):
        self.base = base

    def call(self, path, payload=None, raw=None):
        data = None
        headers = {}
        if raw is not None:
            data = raw.encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as exc:
            response = exc
        body = response.read().decode("utf-8")
        return response.status, response.headers.get("Content-Type", ""), body

    def json(self, path, payload=None, raw=None):
        status, content_type, body = self.call(path, payload, raw)
        return status, content_type, json.loads(body)


def start_studio(project_dir, *, extra_args=(), cwd=None, env=None):
    """起一个真实项目服务并等到 health 就绪。"""
    port = free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "studio",
            "--serve",
            str(project_dir),
            "--port",
            str(port),
            *extra_args,
        ],
        cwd=str(cwd or ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    health = wait_health(f"http://127.0.0.1:{port}", timeout=15)
    check(
        health is not None,
        f"Studio 项目 {Path(project_dir).name} 启动成功（端口 {port}）",
    )
    return process, Api(f"http://127.0.0.1:{port}"), port


def stop_studio(process):
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def main():
    temp = Path(tempfile.mkdtemp(prefix="studio_api_"))
    workspace = temp / "workspace"
    workspace.mkdir()
    rng = random.Random(42)
    with (workspace / "data.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["x", "y"])
        for _ in range(200):
            x = rng.uniform(0.0, 10.0)
            writer.writerow([x, 2.0 * x + 1.0 + rng.gauss(0.0, 0.5)])
    os.environ["workspace"] = str(workspace)
    server = None
    thread = None
    try:
        registry = Registry().load(DEFAULT_DIR, strict=False)

        service = EngineService(registry, project=Project(workspace))
        check(isinstance(service, ApiService), "服务实例是 ApiService 的子类")

        web = temp / "web"
        web.mkdir()
        server = StudioServer(("127.0.0.1", 0), service, web)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        api = Api(f"http://127.0.0.1:{server.server_address[1]}")

        # 1) 健康检查
        status, content_type, body = api.json("/api/health")
        check(status == 200, "GET /api/health 返回 200")
        check(content_type == "application/json; charset=utf-8", f"Content-Type = {content_type}")
        check(
            body["ok"] is True
            and body["engine"] == ENGINE_VERSION
            and body["plugins"] == 6
            and body["components"] == 27,
            f"健康检查 {body}（engine {ENGINE_VERSION}）",
        )
        check(check_health(body) == body, "health 响应通过 check_health")

        # 2) 插件列表：std 是内置类型插件，其余插件只出组件
        status, _, body = api.json("/api/plugins")
        plugins = {item["name"]: item for item in body["plugins"]}
        check(
            status == 200
            and set(plugins) == {"std", "core", "fileio", "ml", "split", "table"},
            f"插件 {sorted(plugins)}",
        )
        check(check_plugins(body) == body, "plugins 响应通过 check_plugins")
        total = sum(len(item["components"]) for item in plugins.values())
        check(total == 27, f"组件数 {total}")

        std = plugins["std"]
        check(
            std["version"] == "1.0"
            and std["title"] == "标准类型"
            and std["components"] == [],
            f"std 是内置伪插件：v{std['version']} / {std['title']} / components={std['components']}",
        )
        check(len(std["types"]) == 5, f"std 带出 5 个标准类型：{[t['id'] for t in std['types']]}")
        std_types = {t["id"]: t["desc"] for t in std["types"]}
        check(
            "std_1.0@table" in std_types
            and "std_1.0@model" in std_types
            and bool(std_types["std_1.0@table"])
            and bool(std_types["std_1.0@model"]),
            f"std 类型含 table / model 且描述非空：{std_types}",
        )
        check(
            registry.plugins["std"].source == "<builtin>",
            f"std 来源 {registry.plugins['std'].source}",
        )
        linear = next(c for c in plugins["ml"]["components"] if c["name"] == "LinearRegression")
        data_port = linear["input_schema"]["data"]
        check(
            data_port["types"] == ["std_1.0@table"]
            and data_port["type_labels"] == ["std@table"]
            and data_port["required"] is True
            and data_port["title"] == "训练数据",
            f"ml.LinearRegression.input_schema.data = {data_port}",
        )
        model_port = linear["output_schema"]["model"]
        check(
            model_port["type"] == "std_1.0@model"
            and model_port["type_label"] == "std@model",
            f"ml.LinearRegression.output_schema.model = {model_port}",
        )
        select = next(c for c in plugins["table"]["components"] if c["name"] == "SelectColumns")
        check(
            select["config_schema"]["columns"]["type"] == "array",
            f"table.SelectColumns.columns 是数组：{select['config_schema']['columns']}",
        )
        split_xy = next(c for c in plugins["split"]["components"] if c["name"] == "SplitXY")
        check(
            split_xy["input_schema"]["data"]["types"] == ["std_1.0@table"]
            and split_xy["output_schema"]["x"]["type"] == "std_1.0@table"
            and split_xy["output_schema"]["y"]["type"] == "std_1.0@table",
            "split.SplitXY 输入 data、输出 x/y 都是 std@table",
        )
        load_csv = next(c for c in plugins["fileio"]["components"] if c["name"] == "LoadCSV")
        check(
            load_csv["input_schema"] == {}
            and load_csv["output_schema"]["table"]["type"] == "std_1.0@table",
            "fileio.LoadCSV 无输入、输出 table（std@table）",
        )
        predict = next(c for c in plugins["core"]["components"] if c["name"] == "PredictModel")
        check(
            predict["input_schema"]["model"]["types"] == ["std_1.0@model"]
            and predict["input_schema"]["data"]["types"] == ["std_1.0@table"]
            and predict["output_schema"]["predictions"]["type"] == "std_1.0@table",
            "core.PredictModel 端口全部指向 std 类型",
        )
        check(
            predict["output_schema"]["predictions"]["type_label"] == "std@table",
            "core.PredictModel.predictions 的 type_label = std@table",
        )
        original = registry.components[("ml", "LinearRegression")]
        check(linear["config_schema"] == original.config_schema, "config_schema 原样返回")

        raw = json.loads(DEMO.read_text(encoding="utf-8"))

        # 3) 校验通过
        status, _, body = api.json("/api/validate", {"workflow": raw})
        check(
            status == 200 and body["ok"] is True and body["errors"] == [],
            f"validate 通过，order={body['order']}",
        )
        check(
            body["order"] == ["n1", "n2", "n3", "n4", "n5", "n6", "n7"],
            "拓扑顺序 n1 -> n2 -> n3 -> n4 -> n5 -> n6 -> n7",
        )
        check(check_validate(body) == body, "validate 通过响应通过 check_validate")

        # 4) 校验拒绝
        bad = json.loads(json.dumps(raw))
        bad["nodes"][4]["inputs"]["model"] = {"from": "n1", "port": "table"}
        status, _, body = api.json("/api/validate", {"workflow": bad})
        joined = " | ".join(body["errors"])
        check(
            status == 200 and body["ok"] is False and "类型不匹配" in joined,
            f"validate 拒绝类型错接：{joined}",
        )
        check(body["order"] == [], "校验失败时 order 为空")
        check(check_validate(body) == body, "validate 拒绝响应通过 check_validate")

        # 5) 运行通过
        status, _, body = api.json("/api/run", {"workflow": raw})
        check(status == 200 and body["ok"] is True and body["errors"] == [], "run 执行成功")
        check(check_run(body) == body, "run 成功响应通过 check_run")
        nodes = body["nodes"]
        check(
            [n["id"] for n in nodes] == ["n1", "n2", "n3", "n4", "n5", "n6", "n7"],
            f"节点顺序 {[n['id'] for n in nodes]}",
        )
        check({n["id"] for n in nodes} == set(body["order"]), "ok=true 时 nodes 覆盖全部 order")
        check(all(n["error"] is None for n in nodes), "所有节点 error 均为 null")
        check(
            all(isinstance(n["ms"], (int, float)) and n["ms"] >= 0 for n in nodes),
            "每个节点都带毫秒耗时",
        )
        check(nodes[2]["outputs"]["model"], "n3 输出 model 预览非空")
        check(nodes[4]["outputs"]["predictions"], "n5 输出 predictions 预览非空")
        metrics = nodes[5]["outputs"]["metrics"]
        match = re.search(r"\br2\s+([0-9.]+)", metrics)
        check(match is not None, "n6 指标表含 r2")
        check(float(match.group(1)) > 0.95, f"r2 = {match.group(1)} > 0.95")
        check((workspace / "regression_out.csv").is_file(), "n7 按 ${workspace} 写出 CSV")

        # 5.5) addition 是编辑器私有区：对象 / 字符串都不影响 validate 与 run
        for addition in (
            {
                "client": "workflow-studio",
                "version": 1,
                "positions": {"n1": {"x": 80, "y": 60}},
                "groups": [],
            },
            "editor-private-block",
        ):
            decorated = json.loads(json.dumps(raw))
            decorated["addition"] = addition
            label = type(addition).__name__
            status, _, body = api.json("/api/validate", {"workflow": decorated})
            check(
                status == 200 and body["ok"] is True,
                f"带 addition（{label}）的 validate 应通过：{body.get('errors')}",
            )
            status, _, body = api.json("/api/run", {"workflow": decorated})
            check(
                status == 200 and body["ok"] is True,
                f"带 addition（{label}）的 run 应通过：{body.get('errors')}",
            )

        # 6) 执行期异常：200 + ok:false，已完成的节点照常返回
        broken = json.loads(json.dumps(raw))
        broken["nodes"][5]["config"]["target"] = "nope"
        status, _, body = api.json("/api/run", {"workflow": broken})
        check(status == 200 and body["ok"] is False, "执行期异常返回 200 + ok:false")
        check(bool(body["errors"]), "执行失败时 errors 非空")
        check(check_run(body) == body, "run 失败响应通过 check_run")
        joined = " | ".join(body["errors"])
        check("n6" in joined and "列不存在" in joined, f"错误信息带节点与原因：{joined}")
        by_id = {n["id"]: n for n in body["nodes"]}
        check(
            set(by_id) == {"n1", "n2", "n3", "n4", "n5", "n6"},
            f"已完成节点仍在：{sorted(by_id)}",
        )
        check(by_id["n1"]["error"] is None and by_id["n1"]["outputs"]["table"], "n1 结果保留")
        check(by_id["n3"]["outputs"]["model"], "n3 结果保留")
        check(by_id["n5"]["outputs"]["predictions"], "n5 结果保留")
        check(by_id["n6"]["error"] is not None, "n6 标记失败原因")

        # 7) 环境变量不残留：第一次带 env，第二次不带，运行期各读一次
        os.environ["STUDIO_ENV_TEST"] = "before"
        original_run = server_module.run
        seen = []

        def spy_run(workflow_obj, registry, on_node_done=None):
            seen.append(os.environ.get("STUDIO_ENV_TEST"))
            check(re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", os.environ.get("run_id") or ""), f"Studio run_id 格式正确：{os.environ.get('run_id')!r}")
            return original_run(workflow_obj, registry, on_node_done)

        server_module.run = spy_run
        try:
            with_env = json.loads(json.dumps(raw))
            with_env["env"] = {"STUDIO_ENV_TEST": "one"}
            status, _, body = api.json("/api/run", {"workflow": with_env})
            check(status == 200 and body["ok"] is True, "带 env 的 run 成功")
            status, _, body = api.json("/api/run", {"workflow": raw})
            check(status == 200 and body["ok"] is True, "不带 env 的 run 成功")
            check(seen == ["one", "before"], f"两次运行期环境 = {seen}")
            check(
                os.environ.get("STUDIO_ENV_TEST") == "before",
                "run 结束后环境变量还原到运行前的值",
            )
        finally:
            server_module.run = original_run
            del os.environ["STUDIO_ENV_TEST"]

        # 8) web 目录为空时 GET / 给提示页
        status, content_type, body = api.call("/")
        check(status == 200 and content_type.startswith("text/html"), f"GET / 返回 HTML（{content_type}）")
        check("python tools/build_web.py" in body, "提示页含构建命令")

        # 9) 真实产物目录：静态文件能取到（含子目录），GET / 回 index.html
        (web / "sub").mkdir()
        (web / "app.js").write_text("console.log('studio');\n", encoding="utf-8")
        (web / "sub" / "x.css").write_text(".studio { color: red; }\n", encoding="utf-8")
        (web / "index.html").write_text("<h1>studio-web-ok</h1>", encoding="utf-8")
        (temp / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")

        status, content_type, body = api.call("/static/app.js")
        check(
            status == 200 and "javascript" in content_type and "charset=utf-8" in content_type,
            f"GET /static/app.js 200（{content_type}）",
        )
        check("studio" in body, "/static/app.js 内容正确")

        status, content_type, body = api.call("/static/sub/x.css")
        check(
            status == 200 and content_type.startswith("text/css") and "charset=utf-8" in content_type,
            f"GET /static/sub/x.css 200（{content_type}）",
        )
        check("color: red" in body, "/static/sub/x.css 子目录内容正确")

        # 越界访问：不能读到 web 目录外面的 secret.txt
        for path in ("/static/../secret.txt", "/static/..%2Fsecret.txt"):
            status, content_type, body = api.call(path)
            payload = json.loads(body)
            check(
                status == 404 and content_type.startswith("application/json"),
                f"GET {path} 404 JSON",
            )
            check(payload["ok"] is False and "未知路径" in payload["errors"][0], f"GET {path} 被拒绝")
            check("TOP-SECRET" not in body, f"GET {path} 没有越出 web 目录")

        status, content_type, body = api.call("/static/")
        check(
            status == 404 and content_type.startswith("application/json"),
            "GET /static/ 空路径 404 JSON",
        )
        check("Traceback" not in body, "GET /static/ 不打堆栈")

        status, content_type, body = api.call("/")
        check(
            status == 200 and content_type.startswith("text/html"),
            f"有 index.html 时 GET / 200（{content_type}）",
        )
        check(
            "studio-web-ok" in body and "python tools/build_web.py" not in body,
            "GET / 返回真实 index.html 而不是占位提示页",
        )

        # 10) 未知路径 404，也是 JSON
        status, content_type, body = api.call("/api/nope")
        check(
            status == 404
            and content_type.startswith("application/json")
            and json.loads(body)["ok"] is False,
            "未知路径 404 JSON",
        )
        status, _, body = api.call("/static/missing.js")
        check(status == 404 and json.loads(body)["ok"] is False, "缺失静态文件 404 JSON")

        # 11) 非法 JSON 请求体
        status, _, body = api.json("/api/validate", raw="not json")
        check(
            status == 400 and body == {"ok": False, "errors": ["请求体不是合法 JSON"]},
            f"非法 JSON 请求体 {body}",
        )

        # 12) 真实启动：python -m studio --serve 走 main()，能起服务、health 正常
        port = free_port()
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "studio",
                "--serve",
                str(workspace),
                "--port",
                str(port),
            ],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            health = wait_health(f"http://127.0.0.1:{port}", timeout=10)
            check(health is not None, f"python -m studio --serve --port {port} 启动成功")
            check(
                health["ok"] is True and health["plugins"] >= 1,
                f"真实进程健康检查 {health}",
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        check(process.returncode is not None, "真实进程已退出")

        released = False
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", port))
                released = True
                break
            except OSError:
                time.sleep(0.1)
        check(released, f"端口 {port} 已释放")

        # 13) 安全：内部异常不把本机路径/异常原文回给客户端
        original_health = service.health

        def boom():
            raise RuntimeError("boom at C:\\temp\\secret\\file.txt")

        service.health = boom
        try:
            status, _, body = api.json("/api/health")
        finally:
            service.health = original_health
        raw_body = json.dumps(body, ensure_ascii=False)
        check(status == 500, f"内部异常返回 500（{status}）")
        check(
            body == {"ok": False, "errors": ["服务器内部错误"]},
            f"内部异常响应体 {body}",
        )
        check(
            "secret" not in raw_body and "boom" not in raw_body and "temp" not in raw_body,
            "响应体不含本机路径或异常原文",
        )

        # 15) 契约：载荷违反契约时回具体字段消息，不压平成通用错误
        original_health = service.health

        def broken_health():
            return {"ok": True}

        service.health = broken_health
        try:
            status, _, body = api.json("/api/health")
        finally:
            service.health = original_health
        raw_body = json.dumps(body, ensure_ascii=False)
        check(status == 500 and body["ok"] is False, f"契约违规返回 500 + ok:false（{status}）")
        check(
            body["errors"] == ["health.engine 必须是字符串"],
            f"契约违规回具体字段消息：{body['errors']}",
        )
        check(
            "health" in body["errors"][0]
            and "engine" in body["errors"][0]
            and "服务器内部错误" not in raw_body,
            "错误消息含 health.engine 且不是通用内部错误",
        )
        check(
            "ContractError" not in raw_body
            and "Traceback" not in raw_body
            and "contract.py" not in raw_body,
            "响应体不含异常类名或栈信息",
        )

        # 16) 调试会话：start → WebSocket state → stop → 端口与临时文件清理
        def debug_roundtrip(verbose):
            def expect(condition, message):
                if not condition:
                    raise AssertionError(message)
                if verbose:
                    print(f"[OK] {message}")

            status, _, body = api.json("/api/debug/start", {"workflow": raw})
            expect(status == 200 and body.get("ok") is True, f"debug start 成功：{body}")
            expect(check_debug_start(body) == body, "debug start 响应通过 check_debug_start")
            session = body["session"]
            port = body["port"]
            token = body["token"]
            with ws_connect(
                f"ws://127.0.0.1:{port}/?token={token}",
                open_timeout=5,
                close_timeout=2,
            ) as websocket:
                websocket.send(json.dumps({"cmd": "state"}))
                message = json.loads(websocket.recv(timeout=5))
            expect(message.get("type") == "state", f"调试 WebSocket 收到 state：{message.get('type')}")
            status, _, body = api.json("/api/debug/stop", {"session": session})
            expect(status == 200 and body.get("ok") is True, f"debug stop 成功：{body}")
            expect(check_debug_stop(body) == body, "debug stop 响应通过 check_debug_stop")
            expect(wait_port_closed(port), f"stop 后调试端口 {port} 已关闭")
            expect(not debug_path(session, "json").exists(), "调试工作流临时文件已删除")
            expect(not debug_path(session, "port").exists(), "调试端口文件已删除")

        debug_roundtrip(verbose=True)
        # 同一动作连跑 20 次：就绪判定偶发把别人的监听当成自己的钩子，这条能抓住
        started = time.monotonic()
        failures = []
        for _ in range(20):
            try:
                debug_roundtrip(verbose=False)
            except AssertionError as exc:
                failures.append(str(exc))
        check(
            not failures,
            f"start→state→stop 连跑 20 次全过（{time.monotonic() - started:.1f}s，失败 {len(failures)} 次）",
        )

        # 17) 未知调试会话
        status, _, body = api.json("/api/debug/stop", {"session": "no-such-session"})
        check(
            status == 200 and body.get("ok") is False and bool(body.get("errors")),
            f"未知 session 回 ok:false：{body}",
        )
        check(check_debug_stop(body) == body, "未知 session 响应通过 check_debug_stop")

        # 18) 同一时刻只允许一个调试会话：第二次 start 关掉第一个
        status, _, first = api.json("/api/debug/start", {"workflow": raw})
        status, _, second = api.json("/api/debug/start", {"workflow": raw})
        check(first.get("ok") and second.get("ok"), "连续两次 debug start 都成功")
        check(wait_port_closed(first["port"]), f"第一个调试端口 {first['port']} 已关闭")
        check(port_open(second["port"]), f"第二个调试端口 {second['port']} 可连")
        check(not debug_path(first["session"], "port").exists(), "第一个会话的端口文件已删除")
        check(debug_path(second["session"], "port").exists(), "第二个会话的端口文件已落盘")
        status, _, body = api.json("/api/debug/stop", {"session": second["session"]})
        check(status == 200 and body.get("ok") is True, "第二个调试会话已停止")

        # 19) 超时路径：钩子起了但不监听 → 10 秒超时、无残留
        slow_hook = temp / "slow_hook"
        slow_hook.mkdir()
        (slow_hook / "hook.py").write_text(
            "import time\n\n\n"
            "def install(ctx):\n"
            "    pass\n\n\n"
            "def serve(execution):\n"
            "    time.sleep(60)\n",
            encoding="utf-8",
        )
        slow = DebugManager(hook_dir=slow_hook)
        before = sorted(DEBUG_DIR.glob("debug_*"))
        try:
            started = time.monotonic()
            result = slow.start(raw)
            elapsed = time.monotonic() - started
        finally:
            slow.shutdown()
        check(result.get("ok") is False, f"超时调试 start 回 ok:false：{result.get('errors')}")
        check(check_debug_start(result) == result, "超时响应通过 check_debug_start")
        check(elapsed >= 9.5, f"确实等到 10 秒超时（{elapsed:.1f}s）")
        check(
            any("端口文件" in item for item in result["errors"]),
            f"超时错误含原因：{result['errors']}",
        )
        check(slow.active is False, "超时后没有活动会话")
        check(
            sorted(DEBUG_DIR.glob("debug_*")) == before,
            "超时后无调试临时文件残留",
        )

        # 20) 假监听不被当成就绪：端口被别人的监听占着时必须失败，不能回 ok:true
        foreign = socket.socket()
        foreign.bind(("127.0.0.1", 0))
        foreign.listen()
        foreign_port = foreign.getsockname()[1]
        # 旧实现自己挑端口、再用「连得上」判定就绪；这里把候选端口钉在假监听上。
        # 修复后 _free_port 已删除，这行不再被调用——旧实现会把假监听当成自己的钩子。
        legacy_free_port = getattr(debug_module, "_free_port", None)
        debug_module._free_port = lambda: foreign_port
        faked = DebugManager(hook_dir=slow_hook)
        before = sorted(DEBUG_DIR.glob("debug_*"))
        try:
            started = time.monotonic()
            result = faked.start(raw)
            elapsed = time.monotonic() - started
        finally:
            faked.shutdown()
            if legacy_free_port is None:
                del debug_module._free_port
            else:
                debug_module._free_port = legacy_free_port
            foreign.close()
        check(result.get("ok") is False, f"假监听没被当成就绪：{result}")
        check(check_debug_start(result) == result, "假监听响应通过 check_debug_start")
        check(elapsed >= 9.5, f"假监听路径等满超时（{elapsed:.1f}s）")
        check(faked.active is False, "假监听失败后没有活动会话")
        check(
            sorted(DEBUG_DIR.glob("debug_*")) == before,
            "假监听失败后无调试临时文件残留",
        )

        # 21) 子进程提前崩：钩子路径不存在 → 快速失败并带 stderr 尾部
        broken = DebugManager(hook_dir=temp / "no_such_hook")
        before = sorted(DEBUG_DIR.glob("debug_*"))
        started = time.monotonic()
        result = broken.start(raw)
        elapsed = time.monotonic() - started
        check(result.get("ok") is False, "崩溃调试 start 回 ok:false")
        check(check_debug_start(result) == result, "崩溃响应通过 check_debug_start")
        check(elapsed < 8, f"提前崩溃没有等满超时（{elapsed:.1f}s）")
        check(
            any("钩子" in item or "不存在" in item for item in result["errors"]),
            f"错误带子进程 stderr：{result['errors']}",
        )
        check(broken.active is False, "崩溃后没有活动会话")
        check(
            sorted(DEBUG_DIR.glob("debug_*")) == before,
            "崩溃后无调试临时文件残留",
        )

        # 22) 真实 Studio 进程把项目 plugins/ 与 -e 透传给调试子进程
        probe_src = temp / "probe_src"
        probe_project = temp / "probe_project"
        probe_plugins = probe_project / "plugins"
        probe_src.mkdir()
        probe_plugins.mkdir(parents=True)
        (probe_src / "__init__.py").write_text("", encoding="utf-8")
        (probe_src / "components.py").write_text(
            "import os\n\n"
            "from engine.api import Component\n\n"
            "PLUGIN_NAME = 'probe'\n"
            "PLUGIN_VERSION = '0.1'\n"
            "PLUGIN_TITLE = '透传探针'\n\n\n"
            "class Probe(Component):\n"
            "    name = 'Probe'\n"
            "    title = '透传探针'\n"
            "    desc = '验证项目 plugins 与 -e 透传'\n\n"
            "    @staticmethod\n"
            "    def config_schema():\n"
            "        return {}\n\n"
            "    @staticmethod\n"
            "    def input_schema():\n"
            "        return {}\n\n"
            "    @staticmethod\n"
            "    def output_schema():\n"
            "        return {'out': {'type': 'std_1.0@string', 'title': '标记'}}\n\n"
            "    def __init__(self, config):\n"
            "        del config\n"
            "        if os.environ.get('PROBE_FLAG') != 'yes':\n"
            "            raise RuntimeError('PROBE_FLAG 没有透传到调试子进程')\n\n"
            "    def invoke(self):\n"
            "        return {'out': 'ok'}\n\n\n"
            "COMPONENTS = [Probe]\n",
            encoding="utf-8",
        )
        with zipfile.ZipFile(
            probe_plugins / "probe.zip", "w", zipfile.ZIP_DEFLATED
        ) as archive:
            archive.write(probe_src / "__init__.py", "probe/__init__.py")
            archive.write(probe_src / "components.py", "probe/components.py")

        probe_port = free_port()
        probe_studio = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "studio",
                "--serve",
                str(probe_project),
                "--port",
                str(probe_port),
                "-e",
                "PROBE_FLAG=yes",
            ],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            probe_health = wait_health(f"http://127.0.0.1:{probe_port}", timeout=10)
            check(
                probe_health is not None and probe_health["plugins"] == 7,
                f"探针 Studio 健康检查 {probe_health}",
            )
            probe_api = Api(f"http://127.0.0.1:{probe_port}")
            probe_workflow = {
                "name": "probe",
                "nodes": [
                    {
                        "id": "p1",
                        "plugin": "probe",
                        "component": "Probe",
                        "config": {},
                        "inputs": {},
                    }
                ],
            }
            status, _, body = probe_api.json(
                "/api/debug/start", {"workflow": probe_workflow}
            )
            check(
                status == 200 and body.get("ok") is True,
                f"透传后调试子进程启动成功：{body.get('errors')}",
            )
            status, _, body = probe_api.json(
                "/api/debug/stop", {"session": body["session"]}
            )
            check(status == 200 and body.get("ok") is True, "透传调试会话已停止")
        finally:
            probe_studio.terminate()
            try:
                probe_studio.wait(timeout=10)
            except subprocess.TimeoutExpired:
                probe_studio.kill()
                probe_studio.wait()
        check(probe_studio.returncode is not None, "探针 Studio 进程已退出")

        # 23) 父进程被强杀：Windows Job Object 带着调试子进程一起退出
        if os.name == "nt":
            doomed_port = free_port()
            doomed = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "studio",
                    "--serve",
                    str(workspace),
                    "--port",
                    str(doomed_port),
                ],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            session_id = None
            child_port = None
            try:
                check(
                    wait_health(f"http://127.0.0.1:{doomed_port}", timeout=10) is not None,
                    f"强杀用例 Studio 启动成功（端口 {doomed_port}）",
                )
                status, _, body = Api(f"http://127.0.0.1:{doomed_port}").json(
                    "/api/debug/start", {"workflow": raw}
                )
                check(status == 200 and body.get("ok") is True, "强杀用例 debug start 成功")
                session_id = body["session"]
                child_port = body["port"]
                child_pids = children_of(doomed.pid)
                check(len(child_pids) == 1, f"找到调试子进程 PID {child_pids}")
                doomed.terminate()  # 直接杀父进程，不触发任何清理
                doomed.wait(timeout=10)
                check(
                    wait_port_closed(child_port, timeout=5),
                    f"父进程被强杀后调试端口 {child_port} 5 秒内关闭",
                )
                check(
                    wait_pid_gone(child_pids[0], timeout=5),
                    f"调试子进程 {child_pids[0]} 随父进程退出，没有残留",
                )
            finally:
                if doomed.poll() is None:
                    doomed.kill()
                    doomed.wait(timeout=10)
                if session_id:
                    # 强杀父进程来不及清理：两个临时文件都要手工删掉
                    for suffix in ("json", "port"):
                        debug_path(session_id, suffix).unlink(missing_ok=True)

        # 24) 同端口起第二个 Studio：非 0 退出，stderr 说明无法监听
        holder_port = free_port()
        holder = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "studio",
                "--serve",
                str(workspace),
                "--port",
                str(holder_port),
            ],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            check(
                wait_health(f"http://127.0.0.1:{holder_port}", timeout=10) is not None,
                f"占用端口 {holder_port} 的 Studio 已启动",
            )
            err_path = temp / "dup.err"
            with err_path.open("wb") as err_file:
                duplicate = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "studio",
                        "--serve",
                        str(workspace),
                        "--port",
                        str(holder_port),
                    ],
                    cwd=str(ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=err_file,
                    env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                    timeout=30,
                )
            err_text = err_path.read_text(encoding="utf-8", errors="replace").strip()
            check(
                duplicate.returncode != 0,
                f"同端口第二个 Studio 启动失败（exit {duplicate.returncode}）",
            )
            check("无法监听" in err_text, f"stderr 说明无法监听：{err_text}")
        finally:
            holder.terminate()
            try:
                holder.wait(timeout=10)
            except subprocess.TimeoutExpired:
                holder.kill()
                holder.wait(timeout=10)

        # 25) shutdown 之后的 start 直接拒绝：挡住 server_close 与在飞 start 的竞态
        closed_manager = DebugManager()
        closed_manager.shutdown()
        before = sorted(DEBUG_DIR.glob("debug_*"))
        refused = closed_manager.start(raw)
        after = sorted(DEBUG_DIR.glob("debug_*"))
        check(
            refused == {"ok": False, "errors": ["调试管理器已关闭"]},
            f"shutdown 后 start 被拒绝：{refused}",
        )
        check(check_debug_start(refused) == refused, "拒绝响应通过 check_debug_start")
        check(after == before, "被拒绝的 start 不写临时文件")

        # 26) 项目根由 --serve 决定：从别处启动也按项目根解析 ${workspace} 与 plugins/
        project_root = temp / "startup_project"
        rel_plugins = project_root / "plugins"
        rel_plugins.mkdir(parents=True)
        elsewhere = temp / "elsewhere"
        elsewhere.mkdir()
        marker = "REL-WORKSPACE-MARKER-7f3a"
        (project_root / "rel_marker.txt").write_text(marker + "\n", encoding="utf-8")
        relprobe_src = temp / "relprobe_src"
        relprobe_src.mkdir()
        (relprobe_src / "__init__.py").write_text("", encoding="utf-8")
        (relprobe_src / "components.py").write_text(
            "from engine.api import Component, expand_env\n\n"
            "PLUGIN_NAME = 'relprobe'\n"
            "PLUGIN_VERSION = '0.1'\n"
            "PLUGIN_TITLE = '启动目录探针'\n\n\n"
            "class ReadMarker(Component):\n"
            "    name = 'ReadMarker'\n"
            "    title = '读取标记文件'\n"
            "    desc = '用 ${workspace} 读文件，验证调试子进程的 workspace'\n\n"
            "    @staticmethod\n"
            "    def config_schema():\n"
            "        return {'path': {'type': 'string', 'title': '文件', 'required': True}}\n\n"
            "    @staticmethod\n"
            "    def input_schema():\n"
            "        return {}\n\n"
            "    @staticmethod\n"
            "    def output_schema():\n"
            "        return {'content': {'type': 'std_1.0@string', 'title': '内容'}}\n\n"
            "    def __init__(self, config):\n"
            "        self.path = expand_env(config['path'])\n\n"
            "    def invoke(self):\n"
            "        with open(self.path, encoding='utf-8') as handle:\n"
            "            return {'content': handle.read().strip()}\n\n\n"
            "COMPONENTS = [ReadMarker]\n",
            encoding="utf-8",
        )
        with zipfile.ZipFile(rel_plugins / "relprobe.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(relprobe_src / "__init__.py", "relprobe/__init__.py")
            archive.write(relprobe_src / "components.py", "relprobe/components.py")
        rel_workflow = {
            "name": "rel-workspace",
            "nodes": [
                {
                    "id": "p1",
                    "plugin": "relprobe",
                    "component": "ReadMarker",
                    "config": {"path": "${workspace}/rel_marker.txt"},
                    "inputs": {},
                }
            ],
        }
        existing_pythonpath = os.environ.get("PYTHONPATH")
        rel_env = dict(
            os.environ,
            PYTHONPATH=str(ROOT)
            + (os.pathsep + existing_pythonpath if existing_pythonpath else ""),
        )
        rel_env.pop("workspace", None)  # 启动目录由子进程自己的 cwd 决定
        rel_port = free_port()
        rel_studio = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "studio",
                "--serve",
                str(project_root),
                "--port",
                str(rel_port),
            ],
            cwd=str(elsewhere),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=rel_env,
        )
        try:
            rel_health = wait_health(f"http://127.0.0.1:{rel_port}", timeout=10)
            check(
                rel_health is not None and rel_health["plugins"] == 7,
                f"启动目录 Studio 用相对插件目录加载到 7 个插件：{rel_health}",
            )
            rel_api = Api(f"http://127.0.0.1:{rel_port}")
            status, _, body = rel_api.json("/api/run", {"workflow": rel_workflow})
            check(
                status == 200 and body.get("ok") is True,
                f"启动目录 Studio 的 /api/run 成功：{body.get('errors')}",
            )
            run_content = body["nodes"][0]["outputs"]["content"]
            check(marker in run_content, f"/api/run 读到启动目录的文件：{run_content}")

            status, _, body = rel_api.json("/api/debug/start", {"workflow": rel_workflow})
            check(
                status == 200 and body.get("ok") is True,
                f"启动目录 Studio 的 debug start 成功：{body.get('errors')}",
            )
            rel_session = body["session"]
            try:
                with ws_connect(
                    f"ws://127.0.0.1:{body['port']}/?token={body['token']}",
                    open_timeout=5,
                    close_timeout=2,
                ) as websocket:
                    websocket.send(json.dumps({"cmd": "run_node", "id": "p1"}))
                    deadline = time.monotonic() + 10
                    debug_state = None
                    while debug_state is None and time.monotonic() < deadline:
                        message = json.loads(websocket.recv(timeout=5))
                        if message.get("type") == "error":
                            raise AssertionError(f"调试 run_node 失败：{message.get('message')}")
                        if message.get("type") != "state":
                            continue
                        data = message["data"]
                        if data["nodes"].get("p1", {}).get("status") == "fresh":
                            debug_state = data
                    check(debug_state is not None, "调试子进程 run_node p1 完成")
                debug_content = debug_state["nodes"]["p1"]["outputs"]["content"]
                check(marker in debug_content, f"调试子进程读到启动目录的文件：{debug_content}")
                check(debug_content == run_content, "/api/run 与调试子进程指向同一个文件")
            finally:
                status, _, body = rel_api.json("/api/debug/stop", {"session": rel_session})
                check(status == 200 and body.get("ok") is True, "启动目录调试会话已停止")
        finally:
            rel_studio.terminate()
            try:
                rel_studio.wait(timeout=10)
            except subprocess.TimeoutExpired:
                rel_studio.kill()
                rel_studio.wait()
        check(rel_studio.returncode is not None, "启动目录 Studio 已退出")

        # 27) 项目形状：root / name / launcher / 插件计数 / skipped / errors
        status, _, body = api.json("/api/project")
        check(status == 200, "GET /api/project 返回 200")
        check(
            body["ok"] is True
            and body["root"] == str(workspace.resolve())
            and body["name"] == "workspace"
            and body["launcher"] is None,
            f"project 形状 {body}",
        )
        check(
            body["plugins"] == {"global": 5, "project": 0}
            and body["skipped"] == []
            and body["errors"] == [],
            f"project 插件概况 {body['plugins']} / skipped={body['skipped']}",
        )

        # 28) tree：目录在前、文件带 size、目录不带
        (workspace / "subdir").mkdir(exist_ok=True)
        note_text = "你好，项目\n第二行"
        note_bytes = note_text.encode("utf-8")
        status, _, body = api.json(
            "/api/file", {"path": "note.txt", "text": note_text}
        )
        check(
            status == 200 and body["ok"] is True and body["size"] == len(note_bytes),
            f"写文件 size 按字节 {body}",
        )
        check(
            (workspace / "note.txt").read_bytes() == note_bytes,
            "盘上字节与写入一致",
        )
        status, _, body = api.json("/api/file?path=note.txt")
        check(
            status == 200
            and body["ok"] is True
            and body["kind"] == "text"
            and body["text"] == note_text
            and body["size"] == len(note_bytes),
            f"读文件往返 {body['kind']} / {body['size']}",
        )

        status, _, body = api.json("/api/tree?path=")
        entries = body["entries"]
        kinds = [entry["kind"] for entry in entries]
        check(
            status == 200
            and body["ok"] is True
            and kinds == sorted(kinds, key=lambda kind: kind != "dir"),
            f"tree 目录在前：{[(e['name'], e['kind']) for e in entries]}",
        )
        dir_entry = next(e for e in entries if e["name"] == "subdir")
        file_entry = next(e for e in entries if e["name"] == "note.txt")
        check(dir_entry["kind"] == "dir" and "size" not in dir_entry, "目录条目不带 size")
        check(
            file_entry["kind"] == "file" and file_entry["size"] == len(note_bytes),
            f"文件条目带 size：{file_entry}",
        )
        status, _, body = api.json("/api/tree?path=subdir")
        check(
            status == 200 and body["ok"] is True and body["entries"] == [],
            "空目录 tree 为空",
        )

        # 29) 路径越界一律拒绝，项目外不落文件
        outside = temp / "outside.txt"
        outside.write_text("SECRET-OUTSIDE", encoding="utf-8")
        for rel in (
            "../outside.txt",
            str(outside),
            "C:\\x",
            "\\\\server\\share\\x",
            "..\\outside.txt",
        ):
            status, _, body = api.json(
                "/api/file?path=" + urllib.parse.quote(rel, safe="")
            )
            check(
                status == 200 and body["ok"] is False and bool(body["errors"]),
                f"越界读被拒 {rel!r}：{body.get('errors')}",
            )
        status, _, body = api.json(
            "/api/file", {"path": "../outside_write.txt", "text": "x"}
        )
        check(
            status == 200 and body["ok"] is False,
            f"越界写被拒：{body.get('errors')}",
        )
        check(
            not (temp / "outside_write.txt").exists(),
            "越界写不能在项目外落文件",
        )
        # 链接逃逸：_rel_parts 挡不住，必须靠 resolve 后的根内判定
        link = workspace / "escape_link"
        if os.name == "nt":
            made = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(temp)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            check(made.returncode == 0, "应为越界用例创建 junction")
        else:
            os.symlink(temp, link, target_is_directory=True)
        status, _, body = api.json(
            "/api/file?path=" + urllib.parse.quote("escape_link/outside.txt", safe="")
        )
        check(
            status == 200 and body["ok"] is False,
            f"链接越界读被拒：{body.get('errors')}",
        )
        status, _, body = api.json(
            "/api/file",
            {"path": "escape_link/outside_write.txt", "text": "x"},
        )
        check(
            status == 200 and body["ok"] is False,
            f"链接越界写被拒：{body.get('errors')}",
        )
        check(
            not (temp / "outside_write.txt").exists(),
            "链接越界写不能在项目外落文件",
        )
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()
        status, _, body = api.json("/api/file?path=missing.txt")
        check(
            status == 200 and body["ok"] is False and bool(body["errors"]),
            f"缺失文件 ok:false：{body}",
        )

        # 30) 二进制与 >1 MiB
        (workspace / "bin.dat").write_bytes(b"\x00\x01\x02\xff")
        status, _, body = api.json("/api/file?path=bin.dat")
        check(
            status == 200 and body["kind"] == "binary" and body["text"] is None,
            f"二进制判 binary：{body}",
        )
        big = "a" * (1024 * 1024 + 1)
        (workspace / "big.txt").write_text(big, encoding="utf-8")
        status, _, body = api.json("/api/file?path=big.txt")
        check(
            status == 200
            and body["kind"] == "too_large"
            and body["text"] is None
            and body["size"] == len(big),
            f">1MiB 判 too_large：{body['kind']} / {body['size']}",
        )

        # 31) mkdir / rename / delete 成功与失败路径
        status, _, body = api.json("/api/mkdir", {"path": "newdir"})
        check(
            status == 200 and body["ok"] is True and (workspace / "newdir").is_dir(),
            f"mkdir 成功：{body}",
        )
        status, _, body = api.json("/api/mkdir", {"path": "newdir"})
        check(
            status == 200 and body["ok"] is False,
            f"mkdir 已存在 ok:false：{body.get('errors')}",
        )

        (workspace / "newdir" / "a.txt").write_text("a", encoding="utf-8")
        status, _, body = api.json(
            "/api/rename", {"path": "newdir/a.txt", "new_name": "b.txt"}
        )
        check(
            status == 200
            and body["ok"] is True
            and body["path"] == "newdir/b.txt"
            and (workspace / "newdir" / "b.txt").is_file()
            and not (workspace / "newdir" / "a.txt").exists(),
            f"rename 成功：{body}",
        )
        (workspace / "newdir" / "c.txt").write_text("c", encoding="utf-8")
        status, _, body = api.json(
            "/api/rename", {"path": "newdir/c.txt", "new_name": "b.txt"}
        )
        check(
            status == 200 and body["ok"] is False,
            f"rename 撞已有名 ok:false：{body.get('errors')}",
        )
        status, _, body = api.json(
            "/api/rename", {"path": "newdir/c.txt", "new_name": "sub/x"}
        )
        check(
            status == 200 and body["ok"] is False,
            f"rename 新名带分隔符被拒：{body.get('errors')}",
        )

        status, _, body = api.json("/api/delete", {"path": "newdir"})
        check(
            status == 200 and body["ok"] is False,
            f"delete 非空目录 ok:false：{body.get('errors')}",
        )
        status, _, body = api.json("/api/delete", {"path": "newdir/b.txt"})
        check(status == 200 and body["ok"] is True, f"delete 文件成功：{body}")
        status, _, body = api.json("/api/delete", {"path": "newdir/c.txt"})
        check(status == 200 and body["ok"] is True, f"delete 遗留文件成功：{body}")
        status, _, body = api.json("/api/delete", {"path": "newdir"})
        check(status == 200 and body["ok"] is True, f"delete 空目录成功：{body}")
        status, _, body = api.json("/api/delete", {"path": "."})
        check(
            status == 200 and body["ok"] is False,
            f"delete 根被拒：{body.get('errors')}",
        )

        # 32) 项目 plugins 里的非插件 zip：skipped 一条、source=project、ok:true
        skipped_project = temp / "skipped_project"
        (skipped_project / "plugins").mkdir(parents=True)
        with zipfile.ZipFile(
            skipped_project / "plugins" / "not_a_plugin.zip", "w"
        ) as archive:
            archive.writestr("readme.txt", "not a plugin")
        skipped_studio = None
        try:
            skipped_studio, skipped_api, _ = start_studio(skipped_project)
            status, _, body = skipped_api.json("/api/project")
            check(
                status == 200
                and body["ok"] is True
                and len(body["skipped"]) == 1
                and body["skipped"][0]["file"] == "not_a_plugin.zip"
                and body["skipped"][0]["source"] == "project",
                f"项目 plugins 里的坏 zip 进 skipped：{body['skipped']}",
            )
            status, _, health_body = skipped_api.json("/api/health")
            check(
                health_body["plugins"] == 6,
                f"跳过坏 zip 后仍有 6 个插件：{health_body}",
            )
        finally:
            if skipped_studio is not None:
                stop_studio(skipped_studio)

        # 33) 与全局插件同名：project() ok:false、计数 0，文件接口照常
        conflict_project = temp / "conflict_project"
        (conflict_project / "plugins").mkdir(parents=True)
        shutil.copyfile(
            DEFAULT_DIR / "core.zip", conflict_project / "plugins" / "core.zip"
        )
        conflict_studio = None
        try:
            conflict_studio, conflict_api, _ = start_studio(conflict_project)
            status, _, health_body = conflict_api.json("/api/health")
            check(
                health_body["plugins"] == 0 and health_body["components"] == 0,
                f"冲突时 health 计数为 0：{health_body}",
            )
            status, _, body = conflict_api.json("/api/project")
            joined = " | ".join(body["errors"])
            check(
                status == 200 and body["ok"] is False,
                f"冲突时 project ok:false：{joined}",
            )
            check("插件名重复" in joined, f"错误含插件名重复：{joined}")
            check(
                str((DEFAULT_DIR / "core.zip").resolve()) in joined
                and str((conflict_project / "plugins" / "core.zip").resolve())
                in joined,
                f"错误含两个绝对路径：{joined}",
            )
            status, _, body = conflict_api.json("/api/validate", {"workflow": raw})
            check(status == 200 and body["ok"] is False, "冲突时 validate 回 ok:false")
            status, _, body = conflict_api.json("/api/tree?path=")
            check(status == 200 and body["ok"] is True, "冲突时文件接口照常")
            status, _, body = conflict_api.json(
                "/api/file", {"path": "still_works.txt", "text": "ok"}
            )
            check(
                body["ok"] is True
                and (conflict_project / "still_works.txt").is_file(),
                "冲突时写文件照常",
            )
        finally:
            if conflict_studio is not None:
                stop_studio(conflict_studio)

        # 34) cwd 就是项目根：相对路径读写都落在项目里，仓库根不出现输出
        cwd_project = temp / "cwd_project"
        cwd_project.mkdir()
        (cwd_project / "data.csv").write_text("x,y\n0,1\n1,3\n", encoding="utf-8")
        out_name = "STUDIO_CWD_OUT.csv"
        check(not (ROOT / out_name).exists(), f"仓库根不应预先存在 {out_name}")
        cwd_workflow = {
            "name": "cwd",
            "nodes": [
                {
                    "id": "n1",
                    "plugin": "fileio",
                    "component": "LoadCSV",
                    "config": {"path": "data.csv"},
                    "inputs": {},
                },
                {
                    "id": "n2",
                    "plugin": "fileio",
                    "component": "SaveCSV",
                    "config": {"path": out_name},
                    "inputs": {"data": {"from": "n1", "port": "table"}},
                },
            ],
        }
        cwd_studio = None
        try:
            cwd_studio, cwd_api, _ = start_studio(cwd_project, cwd=ROOT)
            status, _, body = cwd_api.json("/api/run", {"workflow": cwd_workflow})
            check(
                status == 200 and body["ok"] is True,
                f"相对路径工作流成功：{body.get('errors')}",
            )
            check(
                (cwd_project / out_name).is_file(),
                "SaveCSV 相对路径落在项目根",
            )
            check(
                not (ROOT / out_name).exists(),
                "仓库根不应出现输出文件",
            )
        finally:
            if cwd_studio is not None:
                stop_studio(cwd_studio)
            (ROOT / out_name).unlink(missing_ok=True)

        # 35) --port-file：端口能连；正常退出后端口文件被删
        port_project = temp / "port_project"
        port_project.mkdir()
        port_file = temp / "studio.port"
        wrapper = temp / "studio_stop_after_start.py"
        wrapper.write_text(
            "import sys, threading\n"
            "import studio.server as server\n"
            "original = server.StudioServer.serve_forever\n"
            "def serve_forever(self):\n"
            "    threading.Timer(2.0, self.shutdown).start()\n"
            "    return original(self)\n"
            "server.StudioServer.serve_forever = serve_forever\n"
            "sys.exit(server.main(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        wrapper_env = dict(os.environ, PYTHONPATH=str(ROOT))
        wrapper_env.pop("workspace", None)
        wrap = subprocess.Popen(
            [
                sys.executable,
                str(wrapper),
                "--serve",
                str(port_project),
                "--port",
                "0",
                "--port-file",
                str(port_file),
            ],
            cwd=str(ROOT),
            env=wrapper_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 10
            while not port_file.is_file() and time.monotonic() < deadline:
                time.sleep(0.05)
            check(port_file.is_file(), "--port-file 已写出")
            port_from_file = int(port_file.read_text(encoding="utf-8").strip())
            check(port_open(port_from_file), f"端口文件里的端口 {port_from_file} 可连")
            check(
                wait_health(f"http://127.0.0.1:{port_from_file}", timeout=10)
                is not None,
                "端口文件里的服务 health 正常",
            )
            wrap.wait(timeout=20)
        finally:
            if wrap.poll() is None:
                wrap.kill()
                wrap.wait(timeout=10)
        check(wrap.returncode == 0, f"进程正常退出（exit {wrap.returncode}）")
        check(not port_file.exists(), "正常退出后端口文件已删除")

        # 36) 批 3 起不带 --serve 的 `python -m studio` 是 launcher 默认入口，
        # 不再是「退出 1 并提示用 --serve」；该入口由 tests/test_launcher.py 覆盖。
        print("\nALL OK")
        return 0
    finally:
        os.environ.pop("workspace", None)
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
