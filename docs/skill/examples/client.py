"""workflow-studio 的纯标准库客户端（不依赖 requests）。

    from client import Launcher, StudioError

    launcher = Launcher("http://127.0.0.1:8765")
    opened = launcher.open_project("D:/work/demo")
    project = launcher.project(opened["project"]["url"])

    report = project.validate(flow)      # 业务失败返回 ok=false，不抛错
    if not report["ok"]:
        print(report["errors"])

设计口径：
- 传输层失败（连不上、非 200、响应不是 JSON）抛 StudioError。
- 业务失败（200 + ok:false）原样返回 payload，由调用方判断 ok。
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

__all__ = ["Launcher", "Project", "Studio", "StudioError"]


class StudioError(RuntimeError):
    """传输层失败：连不上、HTTP 非 200、响应不是 JSON。"""


class _Client:
    def __init__(self, base_url, timeout=120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ---- 传输层 ----------------------------------------------------
    def call(self, method, path, payload=None):
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        except OSError as exc:
            raise StudioError(f"{method} {self.base_url + path} 连不上：{exc}") from None
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise StudioError(
                f"{method} {path} 返回的不是 JSON（HTTP {status}）：{raw[:200]!r}"
            ) from None
        if status != 200:
            raise StudioError(f"{method} {path} HTTP {status}：{body}")
        return body

    @staticmethod
    def require(payload):
        """业务层断言：ok 不为 true 就抛 StudioError。"""
        if not payload.get("ok"):
            raise StudioError("；".join(payload.get("errors") or ["ok=false"]))
        return payload


class Launcher(_Client):
    """launcher：项目进程管理 + 目录浏览。"""

    def health(self):
        return self.call("GET", "/api/health")

    def projects(self):
        return self.call("GET", "/api/projects")

    def open_project(self, path):
        return self.call("POST", "/api/projects", {"path": path})

    def close_project(self, root):
        return self.call("POST", "/api/projects/close", {"root": root})

    def restart_project(self, root):
        return self.call("POST", "/api/projects/restart", {"root": root})

    def dirs(self, path=""):
        query = "?path=" + urllib.parse.quote(path, safe="") if path else ""
        return self.call("GET", "/api/fs/dirs" + query)

    def project(self, url=None, root=None, timeout=120.0):
        """取项目服务客户端：给 url，或给已打开项目的 root。

        root 可以用文档里的正斜杠写法（D:/work/demo），也可以直接传响应里的原值
        （D:\\work\\demo）；比较前统一做 normcase+normpath，Windows 下大小写与斜杠都不影响。
        """
        if url is None:
            entries = self.projects()["projects"]
            match = [item for item in entries if os.path.normcase(os.path.normpath(item["root"]))
                     == os.path.normcase(os.path.normpath(root))]
            if not match:
                raise StudioError(f"项目未运行：{root}")
            url = match[0]["url"]
        return Project(url, timeout=timeout)


class Project(_Client):
    """项目服务：文件、插件、校验、执行、调试。"""

    def health(self):
        return self.call("GET", "/api/health")

    def plugins(self):
        return self.call("GET", "/api/plugins")

    def project(self):
        return self.call("GET", "/api/project")

    def tree(self, path=""):
        query = "?path=" + urllib.parse.quote(path, safe="") if path else ""
        return self.call("GET", "/api/tree" + query)

    def read_file(self, path):
        return self.call("GET", "/api/file?path=" + urllib.parse.quote(path, safe=""))

    def stat_file(self, path):
        """只查版本（kind/size/mtime_ns），不读内容；改文件前后用它对比。"""
        return self.call("GET", "/api/stat?path=" + urllib.parse.quote(path, safe=""))

    def write_file(self, path, text):
        return self.call("POST", "/api/file", {"path": path, "text": text})

    def mkdir(self, path):
        return self.call("POST", "/api/mkdir", {"path": path})

    def rename(self, path, new_name):
        return self.call("POST", "/api/rename", {"path": path, "new_name": new_name})

    def delete(self, path):
        return self.call("POST", "/api/delete", {"path": path})

    def validate(self, workflow):
        return self.call("POST", "/api/validate", {"workflow": workflow})

    def run(self, workflow):
        return self.call("POST", "/api/run", {"workflow": workflow})

    def debug_start(self, workflow):
        return self.call("POST", "/api/debug/start", {"workflow": workflow})

    def debug_stop(self, session):
        return self.call("POST", "/api/debug/stop", {"session": session})


class Studio:
    """launcher + 一个已打开项目的一站式入口。"""

    def __init__(self, launcher_url="http://127.0.0.1:8765", root=None):
        self.launcher = Launcher(launcher_url)
        self.root = root
        self.project = None

    def open(self, root):
        payload = self.launcher.open_project(root)
        self.require_open(payload)
        self.root = payload["project"]["root"]
        self.project = self.launcher.project(url=payload["project"]["url"])
        return payload

    def require_open(self, payload):
        if not payload.get("ok"):
            raise StudioError("；".join(payload.get("errors") or ["打开项目失败"]))
        return payload
