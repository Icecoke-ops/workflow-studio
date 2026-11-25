"""launcher（`python -m studio` 默认入口）回归：真进程、真 HTTP、真子进程。

    python tests/test_launcher.py

覆盖：落地页 / health / 目录浏览、项目打开与复用、重启（端口不变）、端口被占用
时重启失败、关闭、父进程被强杀后的孤儿看门狗，以及 launcher_contract 五个校验器。
所有子进程、端口和临时目录在 main() 的 finally 里清干净。
"""

import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio.launcher import LANDING  # noqa: E402
from studio.launcher_contract import (  # noqa: E402
    LauncherError,
    check_close,
    check_dirs,
    check_health,
    check_project_result,
    check_projects,
)

from _harness import check, run_cases  # noqa: E402

START_TIMEOUT = 20.0
ORPHAN_TIMEOUT = 45.0
STUDIO_TEMP = Path(tempfile.gettempdir()) / "workflow-studio"


# ---- 进程 / 端口 --------------------------------------------------------

def _winapi():
    """kernel32 签名；不设 restype 的话 64 位句柄会被截断。"""
    api = ctypes.WinDLL("kernel32", use_last_error=True)
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


# ---- HTTP ---------------------------------------------------------------

def http(base, path, payload=None, method=None, timeout=10.0):
    """返回 (状态码, Content-Type, 原始字节)；4xx/5xx 也照常读正文。"""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    return response.status, response.headers.get("Content-Type", ""), response.read()


def http_json(base, path, payload=None, method=None, timeout=10.0):
    status, content_type, body = http(base, path, payload, method, timeout)
    return status, content_type, json.loads(body.decode("utf-8"))


def _contract(checker, payload):
    """契约校验器不通过要当用例失败报，而不是崩成「意外异常」。"""
    try:
        return checker(payload)
    except LauncherError as exc:
        raise AssertionError(f"{checker.__name__} 拒绝了合法载荷：{exc}") from None


def _must_raise(checker, payload, fragment):
    try:
        checker(payload)
    except LauncherError as exc:
        check(fragment in str(exc), f"错误信息应含 {fragment!r}，实际：{exc!r}")
        return
    raise AssertionError(f"{checker.__name__} 应拒绝畸形载荷 {payload!r}")


# ---- 夹具 ---------------------------------------------------------------

class Context:
    def __init__(self):
        self.temp = Path(tempfile.mkdtemp(prefix="launcher_test_"))
        self.project = self.temp / "project"
        self.project.mkdir()
        self.other = self.temp / "other"
        self.other.mkdir()
        self.proc = None
        self.base = None
        self.port = None
        self.log = None
        self.current = None  # 最近一次 open/restart 返回的项目条目
        self.pids = set()
        self.holder = None

    def track(self, project):
        self.pids.add(project["pid"])
        return project


def launch(ctx):
    """起 launcher 并等 health；端口撞车（极小概率）就换一个重试。"""
    failure = ""
    for _ in range(3):
        port = free_port()
        log = ctx.temp / f"launcher_{port}.log"
        with log.open("wb") as handle:
            proc = subprocess.Popen(
                [sys.executable, "-X", "utf8", "-m", "studio", "--port", str(port)],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            )
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                status, _, payload = http_json(base, "/api/health", timeout=1.0)
            except (OSError, ValueError):
                status, payload = None, None
            if status == 200 and payload.get("ok") is True:
                ctx.proc, ctx.base, ctx.port, ctx.log = proc, base, port, log
                return
            time.sleep(0.05)
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
        failure += log.read_text(encoding="utf-8", errors="replace")
    raise AssertionError(f"launcher 三次都没起来：\n{failure}")


def cleanup(ctx):
    if ctx.holder is not None:
        try:
            ctx.holder.close()
        except OSError:
            pass
    for pid in sorted(ctx.pids):
        if pid_alive(pid):
            kill_pid(pid)
    # TerminateProcess 是异步的：进程还没退干净时它作为 cwd 的临时目录删不掉。
    for pid in sorted(ctx.pids):
        wait_until(lambda pid=pid: not pid_alive(pid), 5)
    if ctx.proc is not None and ctx.proc.poll() is None:
        ctx.proc.kill()
        try:
            ctx.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    for _ in range(3):
        shutil.rmtree(ctx.temp, ignore_errors=True)
        if not ctx.temp.exists():
            break
        time.sleep(0.2)


def studio_temp_files():
    try:
        return set(STUDIO_TEMP.glob("project_*"))
    except OSError:
        return set()


def cleanup_studio_temp(before):
    """launcher 在系统临时目录写 project_*.port/.log；被强杀时会留下，这里收掉。"""
    for path in studio_temp_files() - before:
        try:
            path.unlink()
        except OSError:
            pass


# ---- 用例：launcher 本体 -------------------------------------------------

def case_health(ctx):
    status, content_type, payload = http_json(ctx.base, "/api/health")
    check(status == 200, f"GET /api/health 应为 200，实际 {status}")
    check(
        content_type == "application/json; charset=utf-8",
        f"health Content-Type 不对：{content_type!r}",
    )
    check(payload == {"ok": True}, f"health 载荷不对：{payload!r}")
    _contract(check_health, payload)


def case_landing(ctx):
    status, content_type, body = http(ctx.base, "/")
    expected = LANDING.read_bytes()
    check(status == 200, f"GET / 应为 200，实际 {status}")
    check(
        content_type == "text/html; charset=utf-8",
        f"落地页 Content-Type 不对：{content_type!r}",
    )
    check(
        body == expected,
        f"落地页字节必须与 {LANDING.name} 完全一致：{len(body)} vs {len(expected)}",
    )
    check(body.startswith(b"<!DOCTYPE html>"), "落地页应以 <!DOCTYPE html> 开头")


def case_unknown_path(ctx):
    status, content_type, payload = http_json(ctx.base, "/nope")
    check(status == 404, f"未知 GET 路径应为 404，实际 {status}")
    check(
        content_type == "application/json; charset=utf-8",
        f"404 Content-Type 不对：{content_type!r}",
    )
    check(
        payload == {"ok": False, "errors": ["未知路径：/nope"]},
        f"404 载荷不对：{payload!r}",
    )
    status, _, payload = http_json(ctx.base, "/api/nope", payload={})
    check(status == 404, f"未知 POST 路径应为 404，实际 {status}")
    check(payload.get("ok") is False, f"未知 POST 路径应 ok:false：{payload!r}")


# ---- 用例：目录浏览 -----------------------------------------------------

def case_dirs_root_list(ctx):
    status, _, payload = http_json(ctx.base, "/api/fs/dirs")
    check(status == 200, f"空 path 列目录应为 200，实际 {status}")
    _contract(check_dirs, payload)
    check(payload["parent"] is None, f"盘符列表 parent 必须为 null：{payload['parent']!r}")
    entries = payload["entries"]
    check(bool(entries), "盘符列表不能为空")
    if os.name == "nt":
        check(payload["path"] == "", f"Windows 空 path 应回空串，实际 {payload['path']!r}")
        for entry in entries:
            check(
                "\\" not in entry["name"] and "/" not in entry["name"],
                f"盘符 name 不能带分隔符：{entry['name']!r}",
            )
            check(
                entry["path"] == entry["name"] + "\\",
                f"盘符 path 必须以反斜杠结尾：{entry['path']!r}",
            )
    else:
        check(payload["path"] == "/", f"非 Windows 空 path 应回 /，实际 {payload['path']!r}")
    names = [entry["name"] for entry in entries]
    check(names == sorted(names, key=str.casefold), f"盘符必须排序：{names}")


def case_dirs_children(ctx):
    target = ctx.temp / "tree"
    (target / "beta").mkdir(parents=True)
    (target / "alpha").mkdir()
    (target / "Alpha2").mkdir()
    (target / "a.txt").write_text("x", encoding="utf-8")
    query = "/api/fs/dirs?" + urllib.parse.urlencode({"path": str(target)})
    status, _, payload = http_json(ctx.base, query)
    check(status == 200, f"列子目录应为 200，实际 {status}")
    _contract(check_dirs, payload)
    check(payload["path"] == str(target), f"path 应为 {str(target)!r}，实际 {payload['path']!r}")
    check(payload["parent"] == str(target.parent), f"parent 不对：{payload['parent']!r}")
    names = [entry["name"] for entry in payload["entries"]]
    check(names == ["alpha", "Alpha2", "beta"], f"只列子目录且按名排序，实际 {names}")
    for entry in payload["entries"]:
        check(
            Path(entry["path"]).name == entry["name"],
            f"子目录 path 与 name 不一致：{entry!r}",
        )


def case_dirs_drive_root(ctx):
    target = os.listdrives()[0] if os.name == "nt" else "/"
    query = "/api/fs/dirs?" + urllib.parse.urlencode({"path": target})
    status, _, payload = http_json(ctx.base, query)
    check(status == 200, f"列盘符根应为 200，实际 {status}")
    _contract(check_dirs, payload)
    check(payload["path"] == target, f"盘符根 path 应为 {target!r}，实际 {payload['path']!r}")
    check(payload["parent"] is None, f"盘符根 parent 必须为 null：{payload['parent']!r}")


def case_dirs_bad_path(ctx):
    missing = ctx.temp / "missing"
    query = "/api/fs/dirs?" + urllib.parse.urlencode({"path": str(missing)})
    status, _, payload = http_json(ctx.base, query)
    check(status == 400, f"不存在的目录应为 400，实际 {status}")
    check(payload.get("ok") is False and payload.get("errors"), f"400 载荷不对：{payload!r}")
    check(
        payload["errors"][0].startswith("目录不存在或不是目录："),
        f"400 文案不对：{payload['errors'][0]!r}",
    )
    file_path = ctx.temp / "plain.txt"
    file_path.write_text("x", encoding="utf-8")
    query = "/api/fs/dirs?" + urllib.parse.urlencode({"path": str(file_path)})
    status, _, payload = http_json(ctx.base, query)
    check(status == 400, f"文件（非目录）应为 400，实际 {status}")
    check(payload.get("ok") is False, f"文件（非目录）应 ok:false：{payload!r}")


# ---- 用例：项目生命周期 -------------------------------------------------

def _open(ctx, path):
    status, _, payload = http_json(ctx.base, "/api/projects", payload={"path": str(path)})
    check(status == 200, f"打开项目应为 200，实际 {status}")
    _contract(check_project_result, payload)
    check(payload["ok"] is True, f"打开项目应成功：{payload!r}")
    check(payload["errors"] == [], f"成功时 errors 必须为空：{payload['errors']!r}")
    return ctx.track(payload["project"])


def _close(ctx, root):
    return http_json(ctx.base, "/api/projects/close", payload={"root": str(root)})


def _restart(ctx, root, timeout=10.0):
    return http_json(
        ctx.base, "/api/projects/restart", payload={"root": str(root)}, timeout=timeout
    )


def case_open_project(ctx):
    project = _open(ctx, ctx.project)
    check(project["root"] == str(ctx.project.resolve()), f"root 不对：{project['root']!r}")
    check(project["name"] == ctx.project.name, f"name 不对：{project['name']!r}")
    check(
        project["url"] == f"http://127.0.0.1:{project['port']}",
        f"url 应为项目端口：{project['url']!r}",
    )
    check(pid_alive(project["pid"]), f"项目子进程必须活着：pid={project['pid']}")
    status, _, health = http_json(project["url"], "/api/health")
    check(status == 200 and health.get("ok") is True, f"项目子进程 health 不对：{health!r}")
    ctx.current = project


def case_child_project_info(ctx):
    check(ctx.current is not None, "前置：项目应已打开")
    project = ctx.current
    status, _, payload = http_json(project["url"], "/api/project")
    check(status == 200, f"项目子进程 /api/project 应为 200，实际 {status}")
    check(payload.get("ok") is True, f"子进程 /api/project 应 ok:true：{payload!r}")
    check(
        payload["root"] == str(ctx.project.resolve()),
        f"子进程 root 必须等于项目根：{payload['root']!r}",
    )
    check(payload["name"] == ctx.project.name, f"子进程 name 不对：{payload['name']!r}")
    check(
        payload["launcher"] == ctx.base,
        f"子进程应回传 --launcher 地址：{payload.get('launcher')!r} != {ctx.base!r}",
    )


def case_same_path_reuses_process(ctx):
    check(ctx.current is not None, "前置：项目应已打开")
    first = ctx.current
    second = _open(ctx, ctx.project)
    check(second["pid"] == first["pid"], f"同目录必须复用 pid：{first['pid']} → {second['pid']}")
    check(second["port"] == first["port"], f"同目录必须复用端口：{first['port']} → {second['port']}")
    status, _, listing = http_json(ctx.base, "/api/projects")
    check(status == 200, f"项目列表应为 200，实际 {status}")
    _contract(check_projects, listing)
    roots = [entry["root"] for entry in listing["projects"]]
    check(
        roots.count(str(ctx.project.resolve())) == 1,
        f"同目录只能有一条运行记录：{roots}",
    )


def case_restart_keeps_port(ctx):
    check(ctx.current is not None, "前置：项目应已打开")
    old = ctx.current
    status, _, payload = _restart(ctx, ctx.project)
    check(status == 200, f"重启应为 200，实际 {status}")
    _contract(check_project_result, payload)
    check(payload["ok"] is True, f"重启应成功：{payload!r}")
    new = ctx.track(payload["project"])
    check(new["port"] == old["port"], f"重启必须沿用原端口：{old['port']} → {new['port']}")
    check(new["pid"] != old["pid"], f"重启必须换新进程：pid 仍为 {new['pid']}")
    check(pid_alive(new["pid"]), f"重启后的子进程必须活着：pid={new['pid']}")
    check(
        wait_until(lambda: not pid_alive(old["pid"]), 10),
        f"重启后旧进程必须退出：pid={old['pid']}",
    )
    check(
        wait_until(lambda: port_open(new["port"]), 10),
        f"重启后的端口必须可连：{new['port']}",
    )
    ctx.current = new


def case_restart_port_taken(ctx):
    # 不能先调 close API：close 会把运行记录移除，restart 只会回「项目未运行」。
    # 真实能打到「端口被占」的是记录还在、子进程已死：外部杀掉子进程再占端口。
    project = _open(ctx, ctx.project)
    kill_pid(project["pid"])
    check(
        wait_until(lambda: not pid_alive(project["pid"]), 15),
        f"子进程应被外部杀掉：pid={project['pid']}",
    )
    check(
        wait_until(lambda: not port_open(project["port"]), 15),
        f"子进程死后端口应释放：{project['port']}",
    )
    holder = socket.socket()
    holder.bind(("127.0.0.1", project["port"]))
    holder.listen(1)
    ctx.holder = holder
    try:
        status, _, payload = _restart(ctx, ctx.project, timeout=180.0)
        check(status == 200, f"端口被占时重启仍应回 200：{status}")
        _contract(check_project_result, payload)
        check(payload["ok"] is False, f"端口被占时重启必须失败：{payload!r}")
        check(payload["project"] is None, f"失败时 project 必须为 null：{payload['project']!r}")
        check(
            any("端口被占用" in item for item in payload["errors"]),
            f"errors 应含「端口被占用」：{payload['errors']!r}",
        )
        status, _, listing = http_json(ctx.base, "/api/projects")
        check(
            listing["projects"] == [],
            f"失败后不许偷偷换端口起新实例：{listing['projects']!r}",
        )
    finally:
        holder.close()
        ctx.holder = None
    check(
        wait_until(lambda: not port_open(project["port"]), 10),
        f"释放占位后旧端口不应有监听：{project['port']}",
    )
    ctx.current = None


def case_close_project(ctx):
    project = _open(ctx, ctx.project)
    status, _, payload = _close(ctx, ctx.project)
    check(status == 200, f"关闭应为 200，实际 {status}")
    _contract(check_close, payload)
    check(payload == {"ok": True, "errors": []}, f"关闭载荷不对：{payload!r}")
    check(
        wait_until(lambda: not port_open(project["port"]), 15),
        f"关闭后端口必须释放：{project['port']}",
    )
    check(
        wait_until(lambda: not pid_alive(project["pid"]), 15),
        f"关闭后子进程必须退出：pid={project['pid']}",
    )
    status, _, listing = http_json(ctx.base, "/api/projects")
    _contract(check_projects, listing)
    roots = [entry["root"] for entry in listing["projects"]]
    check(str(ctx.project.resolve()) not in roots, f"关闭后列表不应再有它：{roots}")
    status, _, payload = _close(ctx, ctx.project)
    check(status == 200 and payload["ok"] is False, f"重复关闭应 ok:false：{payload!r}")
    check(
        any("项目未运行" in item for item in payload["errors"]),
        f"重复关闭应报「项目未运行」：{payload['errors']!r}",
    )
    status, _, payload = _close(ctx, ctx.other)
    check(status == 200 and payload["ok"] is False, f"关闭未运行项目应 ok:false：{payload!r}")
    check(
        any("项目未运行" in item for item in payload["errors"]),
        f"未运行项目文案不对：{payload['errors']!r}",
    )
    ctx.current = None


def case_orphan_watchdog(ctx):
    project = _open(ctx, ctx.other)
    check(ctx.proc is not None and ctx.proc.poll() is None, "前置：launcher 应活着")
    launcher_pid = ctx.proc.pid
    ctx.proc.kill()  # TerminateProcess：不走 shutdown，模拟父进程被强杀
    ctx.proc.wait(timeout=10)
    check(not pid_alive(launcher_pid), "launcher 应已被强杀")
    started = time.monotonic()
    gone = wait_until(lambda: not pid_alive(project["pid"]), ORPHAN_TIMEOUT, interval=0.2)
    elapsed = time.monotonic() - started
    check(
        gone,
        f"launcher 被强杀后 {ORPHAN_TIMEOUT:.0f}s 内子进程仍未退出：pid={project['pid']}",
    )
    check(
        wait_until(lambda: not port_open(project["port"]), 10),
        f"子进程退出后端口必须释放：{project['port']}",
    )
    check(elapsed < ORPHAN_TIMEOUT, f"子进程退出耗时 {elapsed:.1f}s，超出余量")
    ctx.current = None


# ---- 用例：launcher_contract 校验器 --------------------------------------

def _project_payload(**overrides):
    payload = {
        "root": r"C:\demo",
        "name": "demo",
        "port": 3000,
        "pid": 4321,
        "url": "http://127.0.0.1:3000",
    }
    payload.update(overrides)
    return payload


def case_contract_health(ctx):
    _contract(check_health, {"ok": True})
    _must_raise(check_health, {"ok": False}, "ok 必须为 true")
    _must_raise(check_health, [], "必须是 dict")


def case_contract_projects(ctx):
    _contract(check_projects, {"ok": True, "errors": [], "projects": [_project_payload()]})
    _contract(check_projects, {"ok": False, "errors": ["引擎不可用"]})
    _must_raise(
        check_projects,
        {"ok": True, "errors": [], "projects": [_project_payload(), _project_payload()]},
        "项目重复",
    )
    _must_raise(check_projects, {"ok": True, "errors": []}, "必须是数组")
    _must_raise(check_projects, {"ok": False, "errors": []}, "至少一条")
    _must_raise(
        check_projects,
        {"ok": True, "errors": [], "projects": [_project_payload(port=True)]},
        "1-65535",
    )


def case_contract_project_result(ctx):
    _contract(check_project_result, {"ok": True, "errors": [], "project": _project_payload()})
    _contract(check_project_result, {"ok": False, "errors": ["起不来"], "project": None})
    _must_raise(check_project_result, {"ok": True, "errors": []}, "必须是 dict")
    _must_raise(
        check_project_result,
        {"ok": False, "errors": ["x"], "project": _project_payload()},
        "project 必须是 null",
    )
    _must_raise(
        check_project_result,
        {"ok": True, "errors": [], "project": _project_payload(pid=0)},
        "正整数",
    )


def case_contract_close(ctx):
    _contract(check_close, {"ok": True, "errors": []})
    _contract(check_close, {"ok": False, "errors": ["项目未运行：x"]})
    _must_raise(check_close, {"ok": False, "errors": []}, "至少一条")


def case_contract_dirs(ctx):
    _contract(check_dirs, {"ok": True, "errors": [], "path": "", "parent": None, "entries": []})
    _contract(
        check_dirs,
        {
            "ok": True,
            "errors": [],
            "path": r"C:\demo",
            "parent": "C:\\",
            "entries": [{"name": "sub", "path": r"C:\demo\sub"}],
        },
    )
    _contract(check_dirs, {"ok": False, "errors": ["目录不存在或不是目录：x"]})
    _must_raise(
        check_dirs,
        {"ok": True, "errors": [], "path": 42, "parent": None, "entries": []},
        "必须是字符串",
    )
    _must_raise(
        check_dirs,
        {"ok": True, "errors": [], "path": "", "parent": "", "entries": []},
        "parent 必须是非空字符串或 null",
    )
    _must_raise(
        check_dirs, {"ok": True, "errors": [], "path": "", "parent": None}, "必须是数组"
    )
    _must_raise(
        check_dirs,
        {
            "ok": True,
            "errors": [],
            "path": "",
            "parent": None,
            "entries": [{"name": "", "path": "x"}],
        },
        "entries[].name",
    )


CASES = [
    ("launcher /api/health 返回 200 与 ok:true", case_health),
    ("launcher / 与落地页 index.html 字节一致", case_landing),
    ("launcher 未知路径 404", case_unknown_path),
    ("dirs 空 path 列盘符", case_dirs_root_list),
    ("dirs 只列子目录且排序、parent 正确", case_dirs_children),
    ("dirs 盘符根 parent 为 null", case_dirs_drive_root),
    ("dirs 不存在/非目录回 400", case_dirs_bad_path),
    ("项目打开：形状与子进程 health", case_open_project),
    ("项目子进程 /api/project 的 root 一致", case_child_project_info),
    ("同一 path 再开复用 pid/port", case_same_path_reuses_process),
    ("重启：端口不变、pid 变且子进程活着", case_restart_keeps_port),
    ("端口被占时重启失败且不换端口", case_restart_port_taken),
    ("关闭：端口释放、列表移除、未运行报错", case_close_project),
    ("launcher 被强杀后子进程自行退出", case_orphan_watchdog),
    ("contract check_health", case_contract_health),
    ("contract check_projects", case_contract_projects),
    ("contract check_project_result", case_contract_project_result),
    ("contract check_close", case_contract_close),
    ("contract check_dirs", case_contract_dirs),
]


def main():
    ctx = Context()
    leftover = studio_temp_files()
    try:
        try:
            launch(ctx)
        except AssertionError as exc:
            print(f"FAIL launcher 启动: {exc}")
            print("\n[FAIL] launcher：1/1 个用例失败")
            return 1
        return run_cases("launcher", [(name, lambda fn=fn: fn(ctx)) for name, fn in CASES])
    finally:
        cleanup(ctx)
        cleanup_studio_temp(leftover)


if __name__ == "__main__":
    sys.exit(main())
