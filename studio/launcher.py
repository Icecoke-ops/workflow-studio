"""固定端口落地页服务：管理项目子进程、浏览服务端目录、发单文件静态页。

    python -m studio [--port 8765]

只监听 127.0.0.1。项目进程由本进程 spawn（``python -m studio --serve DIR``），
每个项目一个子进程，launcher 退出时一起结束。
"""

import argparse
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import BIND_FAILED_EXIT, __version__
from ._http import HTML_TYPE, StudioHTTPHandler, fail, ok, query_path
from .launcher_contract import (
    LauncherApi,
    LauncherError,
    check_close,
    check_dirs,
    check_health,
    check_project_result,
    check_projects,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
LANDING = Path(__file__).resolve().parent / "landing" / "index.html"
TEMP_DIR = Path(tempfile.gettempdir()) / "workflow-studio"
START_TIMEOUT = 10.0
STOP_TIMEOUT = 10.0
RESTART_ATTEMPTS = 10
RESTART_DELAY = 0.1


class Launcher(LauncherApi):
    def __init__(self, base_url=None):
        self.base_url = base_url  # 绑定端口后由 main 填入
        self._lock = threading.Lock()
        self._projects = {}  # normcase(root) -> entry

    # -- 业务 ------------------------------------------------------------
    def health(self):
        return check_health({"ok": True})  # 落地页只认 {"ok": true} 这个最小形状

    def projects(self):
        with self._lock:
            self._prune_locked()
            entries = [self._public(item) for item in self._projects.values()]
        return check_projects(ok(projects=entries))

    def open_project(self, path):
        root = str(Path(path).resolve())
        with self._lock:
            self._prune_locked()
            entry = self._projects.get(_key(root))
            if entry is not None:
                return check_project_result(ok(project=self._public(entry)))
            entry, errors, _ = self._spawn_locked(root, None)
        if entry is None:
            return check_project_result(fail(errors, project=None))
        return check_project_result(ok(project=self._public(entry)))

    def close_project(self, root):
        with self._lock:
            entry = self._projects.pop(_key(root), None)
            if entry is None:
                return check_close(fail([f"项目未运行：{root}"]))
            self._stop_locked(entry)
        return check_close(ok())

    def restart_project(self, root):
        with self._lock:
            entry = self._projects.pop(_key(root), None)
            if entry is None:
                return check_project_result(
                    fail([f"项目未运行：{root}"], project=None)
                )
            port = entry["port"]
            path = entry["root"]
            self._stop_locked(entry)
            for attempt in range(RESTART_ATTEMPTS):
                new_entry, errors, retryable = self._spawn_locked(path, port)
                if new_entry is not None:
                    return check_project_result(ok(project=self._public(new_entry)))
                # 只有端口还没放出来才重试；其它失败立刻回真实原因
                if not retryable:
                    return check_project_result(fail(errors, project=None))
                if attempt + 1 < RESTART_ATTEMPTS:
                    time.sleep(RESTART_DELAY)
            return check_project_result(
                fail(["端口被占用，重启失败"], project=None)
            )

    def dirs(self, path):
        if not path:
            if os.name == "nt":
                drives = sorted(os.listdrives(), key=str.casefold)
                return check_dirs(
                    ok(
                        path="",
                        parent=None,
                        entries=[
                            {"name": drive.rstrip("\\/"), "path": drive}
                            for drive in drives
                        ],
                    )
                )
            path = "/"
        target = Path(path)
        if not target.is_dir():
            return check_dirs(fail([f"目录不存在或不是目录：{path}"]))
        entries = []
        try:
            with os.scandir(target) as scanned:
                for item in scanned:
                    try:
                        if not item.is_dir():
                            continue
                    except OSError:
                        continue
                    entries.append({"name": item.name, "path": item.path})
        except OSError as exc:
            return check_dirs(
                fail([f"无法读取目录 {path}：{exc.strerror or exc}"])
            )
        entries.sort(key=lambda item: item["name"].casefold())
        return check_dirs(
            ok(
                path=str(target),
                parent=_parent_of(target),
                entries=entries,
            )
        )

    def shutdown(self):
        with self._lock:
            for entry in list(self._projects.values()):
                self._stop_locked(entry)
            self._projects.clear()

    # -- 子进程 ----------------------------------------------------------
    def _spawn_locked(self, root, port):
        """起一个项目服务并等它写出端口文件。

        返回 ``(entry, errors, retryable)``；``entry`` 为 None 表示没起来，
        ``retryable`` 由子进程退出码判断（``BIND_FAILED_EXIT`` = 端口没抢到、
        值得重试），不看日志文案。
        """
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        tag = uuid.uuid4().hex[:8]
        port_file = TEMP_DIR / f"project_{tag}.port"
        log_path = TEMP_DIR / f"project_{tag}.log"
        command = [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "studio",
            "--serve",
            root,
            "--port",
            str(port or 0),
            "--port-file",
            str(port_file),
            "--launcher",
            self.base_url,
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        handle = log_path.open("w", encoding="utf-8")
        try:
            process = subprocess.Popen(
                command,
                cwd=str(REPO_ROOT),
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
        except OSError as exc:
            _cleanup(port_file, log_path)
            return None, [f"项目子进程启动失败：{exc}"], False
        finally:
            handle.close()

        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            if process.poll() is not None:
                tail = _tail(log_path)
                _cleanup(port_file, log_path)
                return (
                    None,
                    [f"项目子进程提前退出（exit code {process.returncode}）", *tail],
                    process.returncode == BIND_FAILED_EXIT,
                )
            text = _read_port_file(port_file)
            if text is not None:
                port_file.unlink(missing_ok=True)
                entry = {
                    "root": root,
                    "name": Path(root).name or root,
                    "port": text,
                    "pid": process.pid,
                    "url": f"http://127.0.0.1:{text}",
                    "process": process,
                    "log": log_path,
                }
                self._projects[_key(root)] = entry
                return entry, [], False
            time.sleep(0.05)

        _terminate(process)
        tail = _tail(log_path)
        _cleanup(port_file, log_path)
        return (
            None,
            [f"项目子进程 {START_TIMEOUT:.0f} 秒内没有写出端口文件", *tail],
            False,
        )

    def _stop_locked(self, entry):
        _terminate(entry["process"])
        _cleanup(entry["log"])

    def _prune_locked(self):
        for key, entry in list(self._projects.items()):
            if entry["process"].poll() is not None:
                _cleanup(entry["log"])
                del self._projects[key]

    @staticmethod
    def _public(entry):
        return {
            "root": entry["root"],
            "name": entry["name"],
            "port": entry["port"],
            "pid": entry["pid"],
            "url": entry["url"],
        }


# ---- 工具 --------------------------------------------------------------

def _key(root):
    return os.path.normcase(str(Path(root).resolve()))


def _read_port_file(path):
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return int(text) if text.isdigit() else None


def _tail(path, lines=20):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-lines:]


def _terminate(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _cleanup(*paths):
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _parent_of(path):
    parent = path.parent
    return None if parent == path else str(parent)


# ---- 传输层 ------------------------------------------------------------

class LauncherServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"

    def __init__(self, address, service):
        self.service = service
        super().__init__(address, LauncherHandler)

    def server_close(self):
        self.service.shutdown()
        super().server_close()


class LauncherHandler(StudioHTTPHandler):
    server_version = f"Studio/{__version__}"
    max_body = 1024 * 1024  # 1 MiB

    def _handle_get(self):
        url = urlsplit(self.path)
        path = url.path
        service = self.server.service
        if path == "/api/health":
            self._send_json(HTTPStatus.OK, service.health())
        elif path == "/api/projects":
            self._send_json(HTTPStatus.OK, service.projects())
        elif path == "/api/fs/dirs":
            target = query_path(url)
            if target and not Path(target).is_dir():
                self._bad_request(f"目录不存在或不是目录：{target}")
                return
            self._send_json(HTTPStatus.OK, service.dirs(target))
        elif path == "/":
            self._serve_landing()
        else:
            self._not_found(path)

    def _handle_post(self):
        path = urlsplit(self.path).path
        if path not in (
            "/api/projects",
            "/api/projects/close",
            "/api/projects/restart",
        ):
            self._not_found(path)
            return
        payload = self._read_json()
        if payload is None:
            return
        service = self.server.service
        key = "path" if path == "/api/projects" else "root"
        value = self._string_field(payload, key)
        if value is None:
            return
        if path == "/api/projects":
            if not Path(value).is_dir():
                self._bad_request(f"目录不存在或不是目录：{value}")
                return
            self._send_json(HTTPStatus.OK, service.open_project(value))
        elif path == "/api/projects/close":
            self._send_json(HTTPStatus.OK, service.close_project(value))
        else:
            self._send_json(HTTPStatus.OK, service.restart_project(value))

    # -- 错误 ------------------------------------------------------------
    def _on_error(self, exc):
        if isinstance(exc, LauncherError):
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, fail([str(exc)]))
        else:
            traceback.print_exc()
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR, fail(["服务器内部错误"])
            )

    def _serve_landing(self):
        try:
            body = LANDING.read_bytes()
        except OSError:
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                fail(["落地页尚未构建：studio/landing/index.html"]),
            )
            return
        self._send_body(HTTPStatus.OK, HTML_TYPE, body)


# ---- 启动 --------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="studio", description=f"Studio 落地页与项目进程管理 v{__version__}"
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="监听端口（默认 8765）"
    )
    args = parser.parse_args(argv)

    service = Launcher()
    try:
        server = LauncherServer(("127.0.0.1", args.port), service)
    except OSError as exc:
        print(f"[启动失败] 无法监听 127.0.0.1:{args.port}：{exc}", file=sys.stderr)
        return 1

    port = server.server_address[1]
    service.base_url = f"http://127.0.0.1:{port}"
    print(f"[studio] launcher 监听 http://127.0.0.1:{port}/ （Ctrl+C 停止）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("[studio] 已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
