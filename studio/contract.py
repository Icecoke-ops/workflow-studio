"""Studio HTTP API 的契约。由 Chief 维护，**冻结**。

实现方（studio/server.py）必须做到：

1. 提供一个 :class:`ApiService` 的实现类
2. 每个接口返回前，调用对应的 ``check_*`` 校验载荷
3. 校验不通过就抛 :class:`ContractError`——宁可 500 也不要返回畸形数据

这样接口形状由架构强制，而不是靠约定。
"""

from abc import ABC, abstractmethod


class ContractError(Exception):
    """实现方返回的载荷不符合契约。"""


# --------------------------------------------------------------------------
# 实现方必须实现的四个方法
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# 校验器
# --------------------------------------------------------------------------

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
