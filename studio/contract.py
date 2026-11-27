"""Studio **项目服务** HTTP API 的契约。由 Chief 维护，**冻结**。

launcher（落地页）的接口不在这里，见 ``studio/launcher_contract.py``。


实现方（studio/server.py）必须做到：

1. 提供一个 :class:`ApiService` 的实现类
2. 每个接口返回前，调用对应的 ``check_*`` 校验载荷
3. 校验不通过就抛 :class:`ContractError`——宁可 500 也不要返回畸形数据

这样接口形状由架构强制，而不是靠约定。
"""

from abc import ABC, abstractmethod


class ContractError(Exception):
    """实现方返回的载荷不符合契约。"""


# ---- 实现方必须实现的方法 ----

class ApiService(ABC):
    """Studio 后端业务接口。传输层（HTTP）与业务逻辑必须分开。"""

    @abstractmethod
    def health(self) -> dict:
        """服务与插件概况。"""

    @abstractmethod
    def plugins(self) -> dict:
        """已加载插件的完整能力清单。"""

    @abstractmethod
    def validate(self, workflow) -> dict:
        """只校验，不执行。"""

    @abstractmethod
    def run(self, workflow) -> dict:
        """校验并执行，返回每个节点的耗时与输出预览。"""

    @abstractmethod
    def project(self) -> dict:
        """当前项目与插件加载概况。"""

    @abstractmethod
    def tree(self, path) -> dict:
        """列一层目录；path 是项目内相对路径，空串表示项目根。"""

    @abstractmethod
    def read_file(self, path) -> dict:
        """读文本；二进制或超过上限时只回类型与大小。"""

    @abstractmethod
    def stat_file(self, path) -> dict:
        """查文件版本：文件回 size/mtime_ns，目录与不存在用 kind 区分。"""

    @abstractmethod
    def write_file(self, path, text) -> dict:
        """新建或覆盖文本文件。"""

    @abstractmethod
    def mkdir(self, path) -> dict:
        """新建目录。"""

    @abstractmethod
    def rename(self, path, new_name) -> dict:
        """同目录内重命名文件或目录。"""

    @abstractmethod
    def delete(self, path) -> dict:
        """删除文件或空目录。"""


# ---- 校验器 ----

def _fail(message):
    raise ContractError(message)


def _expect_dict(payload, what):
    if not isinstance(payload, dict):
        _fail(f"{what}: 必须是 dict，实际 {type(payload).__name__}")
    return payload


def _expect_bool(payload, key):
    value = payload.get(key)
    if not isinstance(value, bool):
        _fail(f"字段 {key} 必须是 bool，实际 {type(value).__name__}")
    return value


def _expect_str_list(payload, key):
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        _fail(f"字段 {key} 必须是字符串数组")
    return value


def check_health(payload):
    _expect_dict(payload, "health")
    if payload.get("ok") is not True:
        _fail("health.ok 必须为 true")
    if not isinstance(payload.get("engine"), str):
        _fail("health.engine 必须是字符串")
    for key in ("plugins", "components"):
        if not isinstance(payload.get(key), int) or isinstance(payload.get(key), bool):
            _fail(f"health.{key} 必须是整数")
    return payload


def check_plugins(payload):
    _expect_dict(payload, "plugins")
    plugins = payload.get("plugins")
    if not isinstance(plugins, list):
        _fail("plugins.plugins 必须是数组")

    for plugin in plugins:
        _expect_dict(plugin, "plugin")
        for key in ("name", "version", "title"):
            if not isinstance(plugin.get(key), str):
                _fail(f"plugin.{key} 必须是字符串")
        for entry in plugin.get("types") or []:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                _fail("plugin.types 每项必须是 {id: str, desc: str}")
        components = plugin.get("components")
        if not isinstance(components, list):
            _fail(f"plugin({plugin.get('name')}).components 必须是数组")
        for component in components:
            _check_component(component)
    return payload


def _check_component(component):
    _expect_dict(component, "component")
    for key in ("name", "title", "desc"):
        if not isinstance(component.get(key), str):
            _fail(f"component.{key} 必须是字符串")
    for key in ("config_schema", "input_schema", "output_schema"):
        if not isinstance(component.get(key), dict):
            _fail(f"component({component.get('name')}).{key} 必须是 dict")

    for port, spec in component["input_schema"].items():
        if not isinstance(spec, dict):
            _fail(f"{component['name']}.input_schema.{port} 必须是 dict")
        types = spec.get("types")
        labels = spec.get("type_labels")
        if not isinstance(types, list) or not types:
            _fail(f"{component['name']}.input_schema.{port}.types 必须是非空数组")
        if not isinstance(labels, list) or len(labels) != len(types):
            _fail(f"{component['name']}.input_schema.{port}.type_labels 必须与 types 等长")
        if not isinstance(spec.get("required"), bool):
            _fail(f"{component['name']}.input_schema.{port}.required 必须是 bool")

    for port, spec in component["output_schema"].items():
        if not isinstance(spec, dict) or not isinstance(spec.get("type"), str):
            _fail(f"{component['name']}.output_schema.{port}.type 必须是字符串")
        if not isinstance(spec.get("type_label"), str):
            _fail(f"{component['name']}.output_schema.{port}.type_label 必须是字符串")


def _check_report(payload, what):
    _expect_dict(payload, what)
    ok = _expect_bool(payload, "ok")
    _expect_str_list(payload, "errors")
    _expect_str_list(payload, "warnings")
    order = _expect_str_list(payload, "order")
    if ok and not order:
        _fail(f"{what}: ok=true 时 order 不能为空")
    if not ok and not payload["errors"]:
        _fail(f"{what}: ok=false 时必须给出至少一条 errors")
    return order


def check_validate(payload):
    _check_report(payload, "validate")
    return payload


def check_run(payload):
    order = _check_report(payload, "run")
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        _fail("run.nodes 必须是数组")

    seen = []
    for node in nodes:
        _expect_dict(node, "node")
        if not isinstance(node.get("id"), str):
            _fail("node.id 必须是字符串")
        if not isinstance(node.get("component"), str):
            _fail(f"node({node.get('id')}).component 必须是字符串")
        ms = node.get("ms")
        if not isinstance(ms, (int, float)) or isinstance(ms, bool):
            _fail(f"node({node.get('id')}).ms 必须是数字")
        if not isinstance(node.get("outputs"), dict):
            _fail(f"node({node.get('id')}).outputs 必须是 dict")
        if node.get("error") is not None and not isinstance(node["error"], str):
            _fail(f"node({node.get('id')}).error 必须是 null 或字符串")
        seen.append(node["id"])

    if payload.get("ok") and set(seen) != set(order):
        _fail(f"run: ok=true 时 nodes 覆盖的节点必须与 order 完全一致，实际 {seen} vs {order}")
    return payload


def _check_errors(payload, what):
    errors = payload.get("errors")
    if (
        not isinstance(errors, list)
        or not errors
        or not all(isinstance(item, str) for item in errors)
    ):
        _fail(f"{what}: ok=false 时 errors 必须是非空字符串数组")


def check_debug_start(payload):
    _expect_dict(payload, "debug_start")
    if _expect_bool(payload, "ok"):
        if not isinstance(payload.get("session"), str) or not payload["session"]:
            _fail("debug_start.session 必须是非空字符串")
        port = payload.get("port")
        if (
            not isinstance(port, int)
            or isinstance(port, bool)
            or not 1 <= port <= 65535
        ):
            _fail("debug_start.port 必须是 1-65535 的整数")
        if not isinstance(payload.get("token"), str) or not payload["token"]:
            _fail("debug_start.token 必须是非空字符串")
    else:
        _check_errors(payload, "debug_start")
    return payload


def check_debug_stop(payload):
    _expect_dict(payload, "debug_stop")
    if not _expect_bool(payload, "ok"):
        _check_errors(payload, "debug_stop")
    return payload


# ---- 项目与文件读写 ----

def _expect_ok(payload, what):
    ok = _expect_bool(payload, "ok")
    errors = payload.get("errors")
    if not isinstance(errors, list) or not all(
        isinstance(item, str) for item in errors
    ):
        _fail(f"{what}.errors 必须是字符串数组")
    if not ok and not errors:
        _fail(f"{what}: ok=false 时必须给出至少一条 errors")
    return ok


def _expect_rel_path(payload, key="path", allow_empty=True):
    """项目内相对路径：不许绝对路径、不许 ..、按 / 分段。"""
    value = payload.get(key)
    if not isinstance(value, str):
        _fail(f"{key} 必须是字符串")
    if value.startswith(("/", "\\")) or (len(value) > 1 and value[1] == ":"):
        _fail(f"{key} 必须是项目内相对路径：{value!r}")
    if ".." in value.replace("\\", "/").split("/"):
        _fail(f"{key} 不能包含 ..：{value!r}")
    if not allow_empty and not value:
        _fail(f"{key} 不能为空")
    return value


def check_project(payload):
    _expect_dict(payload, "project")
    _expect_ok(payload, "project")
    if not isinstance(payload.get("root"), str) or not payload["root"]:
        _fail("project.root 必须是非空字符串")
    if not isinstance(payload.get("name"), str):
        _fail("project.name 必须是字符串")
    launcher = payload.get("launcher")
    if launcher is not None and not isinstance(launcher, str):
        _fail("project.launcher 必须是字符串或 null")

    plugins = payload.get("plugins")
    if not isinstance(plugins, dict):
        _fail("project.plugins 必须是 dict")
    for key in ("global", "project"):
        count = plugins.get(key)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            _fail(f"project.plugins.{key} 必须是非负整数")

    skipped = payload.get("skipped")
    if not isinstance(skipped, list):
        _fail("project.skipped 必须是数组")
    for item in skipped:
        _expect_dict(item, "project.skipped[]")
        for key in ("file", "path", "reason"):
            if not isinstance(item.get(key), str):
                _fail(f"project.skipped[].{key} 必须是字符串")
        if item.get("source") not in ("global", "project"):
            _fail("project.skipped[].source 只能是 global 或 project")
    return payload


def check_tree(payload):
    _expect_dict(payload, "tree")
    if _expect_ok(payload, "tree"):
        _expect_rel_path(payload, "path", allow_empty=True)
        entries = payload.get("entries")
        if not isinstance(entries, list):
            _fail("tree.entries 必须是数组")
        for entry in entries:
            _expect_dict(entry, "tree.entries[]")
            if not isinstance(entry.get("name"), str) or not entry["name"]:
                _fail("tree.entries[].name 必须是非空字符串")
            _expect_rel_path(entry, "path", allow_empty=False)
            kind = entry.get("kind")
            if kind not in ("file", "dir"):
                _fail("tree.entries[].kind 只能是 file 或 dir")
            if kind == "file":
                size = entry.get("size")
                if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                    _fail("tree.entries[].size 必须是非负整数")
    return payload


def check_file(payload):
    _expect_dict(payload, "file")
    if _expect_ok(payload, "file"):
        _expect_rel_path(payload, "path", allow_empty=False)
        kind = payload.get("kind")
        if kind not in ("text", "binary", "too_large"):
            _fail("file.kind 只能是 text / binary / too_large")
        size = payload.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            _fail("file.size 必须是非负整数")
        text = payload.get("text")
        if kind == "text":
            if not isinstance(text, str):
                _fail("file.kind=text 时 text 必须是字符串")
        elif text is not None:
            _fail("file.kind 不是 text 时 text 必须是 null")
    return payload


def check_stat(payload):
    _expect_dict(payload, "stat")
    if _expect_ok(payload, "stat"):
        _expect_rel_path(payload, "path", allow_empty=False)
        kind = payload.get("kind")
        if kind not in ("file", "missing", "dir"):
            _fail("stat.kind 只能是 file / missing / dir")
        size = payload.get("size")
        mtime_ns = payload.get("mtime_ns")
        if kind == "file":
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                _fail("stat.kind=file 时 size 必须是非负整数")
            if not isinstance(mtime_ns, int) or isinstance(mtime_ns, bool):
                _fail("stat.kind=file 时 mtime_ns 必须是整数")
        else:
            if size is not None:
                _fail("stat.kind 不是 file 时 size 必须是 null")
            if mtime_ns is not None:
                _fail("stat.kind 不是 file 时 mtime_ns 必须是 null")
    return payload


def check_write_file(payload):
    _expect_dict(payload, "write_file")
    if _expect_ok(payload, "write_file"):
        _expect_rel_path(payload, "path", allow_empty=False)
        size = payload.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            _fail("write_file.size 必须是非负整数")
        mtime_ns = payload.get("mtime_ns")
        if not isinstance(mtime_ns, int) or isinstance(mtime_ns, bool):
            _fail("write_file.mtime_ns 必须是整数")
    return payload


def check_path_result(payload, what):
    """mkdir / rename / delete 共用：成功时回操作后的相对路径。"""
    _expect_dict(payload, what)
    if _expect_ok(payload, what):
        _expect_rel_path(payload, "path", allow_empty=False)
    return payload
