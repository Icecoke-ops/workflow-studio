"""调试会话：把一次运行交给 ``python -m engine run --hook hooks/http_debug`` 子进程。

Studio 只负责起进程、收 stderr 尾巴、停止和清理；执行与 WebSocket 全在钩子里。
就绪信号是钩子写出的端口文件（``hook_port_file``），不是「端口连得上」——连得上
的可能是别人的监听。同一时刻只保留一个会话，新的 ``start`` 先按 ``stop`` 流程关掉旧的。
Windows 上子进程被放进 Job Object（句柄关闭即终止），所以 Studio 被强杀时
子进程会跟着退出，而不是继续占着调试端口。
"""

import ctypes
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from collections import deque
from pathlib import Path

START_TIMEOUT = 10.0
STOP_TIMEOUT = 3.0
LOG_LINES = 200
ROOT = Path(__file__).resolve().parent.parent
TEMP_DIR = Path(tempfile.gettempdir()) / "workflow-studio"

_JOB_KILL_ON_JOB_CLOSE = 0x2000
_JOB_EXTENDED_LIMIT = 9


class DebugManager:
    def __init__(self, extra_args=(), hook_dir=None, workspace=None):
        self.extra_args = list(extra_args)
        self.hook_dir = Path(hook_dir) if hook_dir else ROOT / "hooks" / "http_debug"
        # 子进程 cwd 是仓库根，必须用 -e workspace 显式对齐 Studio 的启动目录
        self.workspace = str(workspace or os.getcwd())
        self._lock = threading.Lock()
        self._session = None
        self._closed = False
        self._warned_job = False

    @property
    def active(self):
        return self._session is not None

    def start(self, workflow):
        with self._lock:
            if self._closed:
                return {"ok": False, "errors": ["调试管理器已关闭"]}
            self._stop_locked()
            session = uuid.uuid4().hex
            token = secrets.token_urlsafe(16)
            TEMP_DIR.mkdir(parents=True, exist_ok=True)
            # 父进程被强杀时这两个文件会残留（进程内来不及清理）；下次 start 用新文件名
            path = TEMP_DIR / f"debug_{session}.json"
            path.write_text(json.dumps(workflow, ensure_ascii=False), encoding="utf-8")
            port_path = TEMP_DIR / f"debug_{session}.port"

            command = [
                sys.executable,
                "-m",
                "engine",
                "run",
                "--hook",
                str(self.hook_dir),
                # 放在其他 -e 之前：用户自己的 -e workspace=... 仍能覆盖
                "-e",
                f"workspace={self.workspace}",
                *self.extra_args,
                # 端口由钩子 bind 时分配、写进 port_path；Studio 不自己挑端口，
                # 否则端口被别人的监听占住时会把别人的钩子当成就绪。
                "-e",
                "hook_port=0",
                "-e",
                f"hook_port_file={port_path}",
                "-e",
                f"hook_token={token}",
                str(path),
            ]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    creationflags=flags,
                )
            except OSError as exc:
                path.unlink(missing_ok=True)
                return {"ok": False, "errors": [f"调试子进程启动失败：{exc}"]}

            state = _Session(session, port_path, path, process)
            self._session = state
            state.job, job_error = _open_job()
            if state.job is not None:
                assigned, job_error = _assign_job(state.job, process.pid)
                if not assigned:
                    _close_job(state.job)
                    state.job = None
            if state.job is None and os.name == "nt" and not self._warned_job:
                self._warned_job = True
                print(
                    "[警告] 无法把调试子进程加入 Windows Job Object"
                    f"（GetLastError={job_error}），Studio 被强杀时子进程可能残留",
                    file=sys.stderr,
                )
            _start_reader(state, process.stderr, state.stderr)

            deadline = time.monotonic() + START_TIMEOUT
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    return self._fail_start(
                        f"调试子进程提前退出（exit code {process.returncode}）"
                    )
                if port_path.exists():
                    port, text = _read_port_file(port_path)
                    if port is None:
                        return self._fail_start(
                            f"调试端口文件内容不是合法端口：{text!r}"
                        )
                    state.port = port
                    return {
                        "ok": True,
                        "session": session,
                        "port": port,
                        "token": token,
                    }
                time.sleep(0.05)
            return self._fail_start(
                f"调试子进程 {START_TIMEOUT:.0f} 秒内没有写出端口文件"
            )

    def stop(self, session):
        with self._lock:
            state = self._session
            if state is None or state.session != session:
                return {"ok": False, "errors": [f"未知调试会话：{session}"]}
            self._stop_locked()
            return {"ok": True}

    def shutdown(self):
        # 与在飞 start 共用这把锁：最坏要等 START_TIMEOUT（10 秒）才拿到锁。
        # 这是正确的（子进程最终会被关掉、不泄漏），代价只是 Ctrl+C 慢一点。
        with self._lock:
            self._closed = True
            self._stop_locked()

    # -- 内部 ------------------------------------------------------------
    def _fail_start(self, reason):
        state = self._session
        self._session = None
        tail = []
        if state is not None:
            _terminate(state.process)
            _close_job(state.job)
            _join_readers(state)
            with state.log_lock:
                tail = list(state.stderr)[-20:]
            state.path.unlink(missing_ok=True)
            state.port_path.unlink(missing_ok=True)
        return {"ok": False, "errors": [reason, *tail]}

    def _stop_locked(self):
        state = self._session
        if state is None:
            return
        self._session = None
        if state.port is not None and state.process.poll() is None:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{state.port}/shutdown", data=b"", timeout=2
                ) as response:
                    response.read()
            except Exception:
                pass
        try:
            state.process.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            _terminate(state.process)
        _close_job(state.job)
        _join_readers(state)
        state.path.unlink(missing_ok=True)
        state.port_path.unlink(missing_ok=True)


class _Session:
    def __init__(self, session, port_path, path, process):
        self.session = session
        self.port = None  # 端口要等钩子写出 port_path 才知道
        self.port_path = port_path
        self.path = path
        self.process = process
        self.job = None
        self.stderr = deque(maxlen=LOG_LINES)
        self.log_lock = threading.Lock()
        self.readers = []


def _read_port_file(path):
    """读钩子写出的端口，返回 ``(端口, 原文)``；不是合法端口时端口为 None。"""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None, ""
    if text.isdigit() and 1 <= int(text) <= 65535:
        return int(text), text
    return None, text


def _terminate(process):
    """先 terminate 等 3 秒，仍不退就 kill；已退出则什么都不做。"""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _start_reader(state, stream, sink):
    def pump():
        try:
            for raw in stream:
                with state.log_lock:
                    sink.append(raw.decode("utf-8", "replace").rstrip("\r\n"))
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    state.readers.append(thread)


def _join_readers(state):
    for thread in state.readers:
        thread.join(timeout=2)


# ---- Windows Job Object：父进程死掉时连带子进程 ---------------------------

class _BasicLimit(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_void_p),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimit),
        ("IoInfo", ctypes.c_uint64 * 6),  # 6 个计数器只占布局，不读
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_WINAPI = None


def _winapi():
    """取 kernel32 并固定签名；不设 restype 的话 64 位句柄会被截断。"""
    global _WINAPI
    if _WINAPI is None:
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
        api.CreateJobObjectW.restype = ctypes.c_void_p
        api.SetInformationJobObject.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        api.SetInformationJobObject.restype = ctypes.c_int
        api.AssignProcessToJobObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        api.AssignProcessToJobObject.restype = ctypes.c_int
        api.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        api.OpenProcess.restype = ctypes.c_void_p
        api.CloseHandle.argtypes = (ctypes.c_void_p,)
        api.CloseHandle.restype = ctypes.c_int
        _WINAPI = api
    return _WINAPI


def _open_job():
    """建一个“句柄关闭即终止成员”的 Job Object；返回 (句柄, GetLastError)。

    非 Windows 不建 job（返回 ``(None, None)``），失败时句柄为 None。
    """
    if os.name != "nt":
        return None, None
    api = _winapi()
    handle = api.CreateJobObjectW(None, None)
    if not handle:
        return None, ctypes.get_last_error()
    limits = _ExtendedLimit()
    limits.BasicLimitInformation.LimitFlags = _JOB_KILL_ON_JOB_CLOSE
    ok = api.SetInformationJobObject(
        handle, _JOB_EXTENDED_LIMIT, ctypes.byref(limits), ctypes.sizeof(limits)
    )
    if not ok:
        error = ctypes.get_last_error()
        api.CloseHandle(handle)
        return None, error
    return handle, None


def _assign_job(job, pid):
    """把进程放进 job；返回 (是否成功, GetLastError)。"""
    api = _winapi()
    process = api.OpenProcess(0x0100 | 0x0001, 0, pid)  # SET_QUOTA | TERMINATE
    if not process:
        return False, ctypes.get_last_error()
    try:
        if api.AssignProcessToJobObject(job, process):
            return True, None
        return False, ctypes.get_last_error()
    finally:
        api.CloseHandle(process)


def _close_job(job):
    if job:
        _winapi().CloseHandle(job)
