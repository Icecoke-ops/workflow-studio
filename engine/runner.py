"""实例化 + 拓扑顺序执行。

先把所有节点实例化好再开跑：初始化阶段的错误一次暴露，
不会跑到一半才炸。
"""

import time
from dataclasses import dataclass

from .errors import ExecutionError


@dataclass
class NodeResult:
    outputs: dict
    ms: float = 0.0


def run(workflow, registry, on_node_done=None):
    instances = {}
    results = {}
    try:
        for node_id in workflow.order:
            node = workflow.nodes[node_id]
            try:
                instances[node_id] = node.entry.cls(node.config)
            except Exception as exc:
                raise ExecutionError(
                    f"节点 {node_id}（{node.entry.full_name}）初始化失败：{exc}",
                    node_id=node_id,
                ) from exc

        for node_id in workflow.order:
            node = workflow.nodes[node_id]
            inputs = {
                port: results[src_id].outputs[src_port]
                for port, (src_id, src_port) in node.inputs.items()
            }
            start = time.perf_counter()
            try:
                returned = instances[node_id].invoke(**inputs)
            except Exception as exc:
                raise ExecutionError(
                    f"节点 {node_id}（{node.entry.full_name}）执行失败：{exc}",
                    node_id=node_id,
                ) from exc
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            result = NodeResult(
                outputs=_check_output(node_id, node.entry, returned, registry),
                ms=elapsed_ms,
            )
            results[node_id] = result
            if on_node_done is not None:
                on_node_done(node_id, result)
    finally:
        for instance in instances.values():
            try:
                instance.close()
            except Exception:
                pass
    return results


def _check_output(node_id, entry, returned, registry):
    if not isinstance(returned, dict):
        raise ExecutionError(
            f"节点 {node_id}（{entry.full_name}）的 invoke 必须返回 dict，"
            f"实际是 {type(returned).__name__}",
            node_id=node_id,
        )
    expected = set(entry.output_schema)
    actual = set(returned)
    if expected != actual:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ExecutionError(
            f"节点 {node_id}（{entry.full_name}）返回端口不匹配："
            f"缺少 {missing}，多余 {extra}",
            node_id=node_id,
        )

    for port, value in returned.items():
        type_id = entry.output_schema[port]["type"]
        contract = registry.models.get(type_id)
        if contract is not None and not isinstance(value, contract):
            methods = "、".join(sorted(getattr(contract, "__abstractmethods__", [])))
            raise ExecutionError(
                f"节点 {node_id}（{entry.full_name}）输出端口 {port} 声称是 {type_id}，"
                f"但 {type(value).__name__} 没有继承 {contract.__name__}"
                f"（该类型要求实现 {methods}）",
                node_id=node_id,
            )
    return returned
