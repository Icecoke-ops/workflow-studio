"""launcher（落地页）HTTP API 的契约。由 Chief 维护，**冻结**。

launcher 是固定端口的独立服务，只管三件事：管理项目进程、给落地页浏览
服务端目录、发那一张单文件静态页。项目内的文件读写与插件接口见
``studio/contract.py``。

实现方（``studio/launcher.py``）必须：

1. 提供 :class:`LauncherApi` 的实现类；
2. 每个接口返回前调用对应的 ``check_*``；
3. 校验不通过抛 :class:`LauncherError`——宁可 500 也不要返回畸形数据。
"""

from abc import ABC, abstractmethod


class LauncherError(Exception):
    """实现方返回的载荷不符合契约。"""


class LauncherApi(ABC):
    """落地页后端的业务接口。"""

    @abstractmethod
    def health(self) -> dict:
        """launcher 存活检查。"""

    @abstractmethod
    def projects(self) -> dict:
        """当前正在运行的项目进程。"""

    @abstractmethod
    def open_project(self, path) -> dict:
        """打开项目：同一目录复用已运行实例，否则起子进程。"""

    @abstractmethod
    def close_project(self, root) -> dict:
        """关闭项目：优雅结束对应的子进程。"""

    @abstractmethod
    def restart_project(self, root) -> dict:
        """重启项目：同一端口起新子进程，让插件重新加载。"""

    @abstractmethod
    def dirs(self, path) -> dict:
        """列服务端目录（只列目录）；path 空串表示盘符 / 根列表。"""


# ---- 校验器 ----

def _fail(message):
    raise LauncherError(message)


def _expect_dict(payload, what):
    if not isinstance(payload, dict):
        _fail(f"{what}: 必须是 dict，实际 {type(payload).__name__}")
    return payload


def _expect_ok(payload, what):
    ok = payload.get("ok")
    if not isinstance(ok, bool):
        _fail(f"{what}.ok 必须是 bool")
    errors = payload.get("errors")
    if not isinstance(errors, list) or not all(
        isinstance(item, str) for item in errors
    ):
        _fail(f"{what}.errors 必须是字符串数组")
    if not ok and not errors:
        _fail(f"{what}: ok=false 时必须给出至少一条 errors")
    return ok


def _check_project(entry):
    _expect_dict(entry, "launcher.project")
    for key in ("root", "name", "url"):
        if not isinstance(entry.get(key), str) or not entry[key]:
            _fail(f"launcher.project.{key} 必须是非空字符串")
    port = entry.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        _fail("launcher.project.port 必须是 1-65535 的整数")
    pid = entry.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        _fail("launcher.project.pid 必须是正整数")


def check_health(payload):
    _expect_dict(payload, "launcher.health")
    if payload.get("ok") is not True:
        _fail("launcher.health.ok 必须为 true")
    return payload


def check_projects(payload):
    _expect_dict(payload, "launcher.projects")
    if _expect_ok(payload, "launcher.projects"):
        projects = payload.get("projects")
        if not isinstance(projects, list):
            _fail("launcher.projects.projects 必须是数组")
        seen = set()
        for entry in projects:
            _check_project(entry)
            if entry["root"] in seen:
                _fail(f"launcher.projects: 项目重复 {entry['root']!r}")
            seen.add(entry["root"])
    return payload


def check_project_result(payload):
    """open / restart 共用：成功时带 project，失败时 project 为 null。"""
    _expect_dict(payload, "launcher.project_result")
    ok = _expect_ok(payload, "launcher.project_result")
    project = payload.get("project")
    if ok:
        _check_project(project)
    elif project is not None:
        _fail("launcher.project_result: ok=false 时 project 必须是 null")
    return payload


def check_close(payload):
    _expect_dict(payload, "launcher.close")
    _expect_ok(payload, "launcher.close")
    return payload


def check_dirs(payload):
    _expect_dict(payload, "launcher.dirs")
    if _expect_ok(payload, "launcher.dirs"):
        path = payload.get("path")
        if not isinstance(path, str):
            _fail("launcher.dirs.path 必须是字符串（空串表示盘符列表）")
        parent = payload.get("parent")
        if parent is not None and (not isinstance(parent, str) or not parent):
            _fail("launcher.dirs.parent 必须是非空字符串或 null")
        entries = payload.get("entries")
        if not isinstance(entries, list):
            _fail("launcher.dirs.entries 必须是数组")
        for entry in entries:
            _expect_dict(entry, "launcher.dirs.entries[]")
            for key in ("name", "path"):
                if not isinstance(entry.get(key), str) or not entry[key]:
                    _fail(f"launcher.dirs.entries[].{key} 必须是非空字符串")
    return payload
