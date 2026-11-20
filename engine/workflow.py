"""工作流 JSON 的解析与校验。

一个校验器收集**全部**错误后一次返回，不在第一个错误处中断。
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import schema as schema_mod
from .env import NAME_RE
from .errors import WorkflowError

ALLOWED_TOP = {"name", "env", "nodes"}
ALLOWED_NODE = {"id", "plugin", "component", "config", "inputs"}
ALLOWED_EDGE = {"from", "port"}


@dataclass
class NodeSpec:
    id: str
    plugin: str
    component: str
    config: dict
    inputs: dict  # {输入端口: (来源节点 id, 来源输出端口)}
    entry: object = None


@dataclass
class Workflow:
    name: str
    nodes: dict
    order: list = field(default_factory=list)
    env: dict = field(default_factory=dict)


@dataclass
class Report:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    workflow: object = None

    @property
    def ok(self):
        return not self.errors

    @property
    def order(self):
        return list(self.workflow.order) if self.workflow else []


def load_workflow(path):
    file_path = Path(path)
    if not file_path.is_file():
        raise WorkflowError(f"工作流文件不存在：{file_path.resolve()}")
    try:
        # utf-8-sig 兼容记事本/PowerShell 写出的 UTF-8 BOM
        text = file_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise WorkflowError(
            f"{file_path.name} 不是 UTF-8 编码，请另存为 UTF-8：{exc}"
        ) from exc
    except OSError as exc:
        raise WorkflowError(f"{file_path.name} 读取失败：{exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"{file_path.name} 不是合法 JSON：{exc}") from exc


def validate(registry, raw):
    report = Report()
    errors = report.errors

    if not isinstance(raw, dict):
        errors.append("工作流必须是 JSON 对象")
        return report

    unknown = set(raw) - ALLOWED_TOP
    if unknown:
        errors.append(f"工作流存在未知字段 {sorted(unknown)}")

    name = raw.get("name", "")
    if not isinstance(name, str):
        errors.append(f"name 必须是字符串，实际 {type(name).__name__}")
        name = ""

    env = raw.get("env", {})
    if not isinstance(env, dict):
        errors.append("env 必须是对象")
        env = {}
    else:
        for key, value in env.items():
            if not isinstance(key, str) or not NAME_RE.match(key):
                errors.append(f"env 变量名不合法：{key!r}")
            if not isinstance(value, str):
                errors.append(f"env.{key} 的值必须是字符串")

    raw_nodes = raw.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        errors.append("nodes 必须是非空数组")
        return report

    nodes = {}
    for index, item in enumerate(raw_nodes):
        where = f"nodes[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where}: 必须是 JSON 对象")
            continue
        unknown = set(item) - ALLOWED_NODE
        if unknown:
            errors.append(f"{where}: 未知字段 {sorted(unknown)}")

        node_id = item.get("id")
        if not isinstance(node_id, str) or not node_id:
            errors.append(f"{where}: id 必须是非空字符串")
            continue
        where = f"nodes[{index}]（{node_id}）"
        if node_id in nodes:
            errors.append(f"{where}: id 重复")
            continue

        plugin = item.get("plugin")
        component = item.get("component")
        if not isinstance(plugin, str) or not plugin:
            errors.append(f"{where}: plugin 必须是非空字符串")
            continue
        if not isinstance(component, str) or not component:
            errors.append(f"{where}: component 必须是非空字符串")
            continue
        entry = registry.get_component(plugin, component)
        if entry is None:
            errors.append(f"{where}: 组件 {plugin}.{component} 不存在")
            continue

        config = item.get("config", {})
        if not isinstance(config, dict):
            errors.append(f"{where}: config 必须是 JSON 对象")
            config = {}
        inputs_raw = item.get("inputs", {})
        if not isinstance(inputs_raw, dict):
            errors.append(f"{where}: inputs 必须是 JSON 对象")
            inputs_raw = {}

        # 先校验原始 config（否则未知参数会被 fill_defaults 静默丢掉），再补默认值
        errors.extend(
            schema_mod.check_config_values(entry.config_schema, config, f"{where}.config")
        )
        config = schema_mod.fill_defaults(entry.config_schema, config)

        inputs = {}
        for port, link in inputs_raw.items():
            if port not in entry.input_schema:
                errors.append(
                    f"{where}.inputs.{port}: 组件没有这个输入端口"
                    f"（可用：{sorted(entry.input_schema) or '无'}）"
                )
                continue
            if not isinstance(link, dict):
                errors.append(f"{where}.inputs.{port}: 必须是 {{from, port}} 对象")
                continue
            unknown = set(link) - ALLOWED_EDGE
            if unknown:
                errors.append(f"{where}.inputs.{port}: 未知字段 {sorted(unknown)}")
            src_id = link.get("from")
            src_port = link.get("port")
            if not isinstance(src_id, str) or not src_id:
                errors.append(f"{where}.inputs.{port}: from 必须是非空字符串")
                continue
            if not isinstance(src_port, str) or not src_port:
                errors.append(f"{where}.inputs.{port}: port 必须是非空字符串")
                continue
            inputs[port] = (src_id, src_port)

        nodes[node_id] = NodeSpec(node_id, plugin, component, config, inputs, entry)

    if len(nodes) != len(raw_nodes):
        return report  # 有节点没解析成功，后面的连线检查会产生连锁噪音

    # ---- 连线与类型 ----
    children = {node_id: [] for node_id in nodes}
    indegree = {node_id: 0 for node_id in nodes}

    for node in nodes.values():
        where = f"nodes（{node.id}）"
        for port, (src_id, src_port) in node.inputs.items():
            source = nodes.get(src_id)
            if source is None:
                errors.append(f"{where}.inputs.{port}: 来源节点 {src_id} 不存在")
                continue
            if src_port not in source.entry.output_schema:
                errors.append(
                    f"{where}.inputs.{port}: 来源节点 {src_id} 没有输出端口 {src_port}"
                    f"（可用：{sorted(source.entry.output_schema)}）"
                )
                continue
            produced = source.entry.output_schema[src_port]["type"]
            accepted = node.entry.input_schema[port]["types"]
            if produced not in accepted:
                errors.append(
                    f"{where}.inputs.{port}: 类型不匹配，来源输出 "
                    f"{registry.short_type(produced)}，本端口需要 "
                    f"{' / '.join(registry.short_type(t) for t in accepted)}"
                )
            indegree[node.id] += 1
            children[src_id].append(node.id)

        for port, spec in node.entry.input_schema.items():
            if spec.get("required", True) and port not in node.inputs:
                errors.append(
                    f"{where}.inputs.{port}: 缺少必填输入"
                    f"（需要 {' / '.join(registry.short_type(t) for t in spec['types'])}）"
                )

    if errors:
        return report

    # ---- 拓扑排序 / 环检测 ----
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    order = []
    while queue:
        node_id = queue.pop(0)
        order.append(node_id)
        for child in children[node_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    if len(order) != len(nodes):
        stuck = sorted(node_id for node_id, degree in indegree.items() if degree > 0)
        errors.append(f"工作流存在环，这些节点无法排序：{stuck}")
        return report

    for node_id, node in nodes.items():
        if not node.inputs and not children[node_id]:
            report.warnings.append(f"节点 {node_id} 是孤立节点（既没有输入也没有下游）")

    report.workflow = Workflow(name=name, nodes=nodes, order=order, env=env)
    return report
