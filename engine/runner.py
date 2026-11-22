"""实例化 + 拓扑顺序执行。

先把所有节点实例化好再开跑：初始化阶段的错误一次暴露，
不会跑到一半才炸。

带钩子的完整驱动是 :func:`execute`；:func:`run` 是 :class:`Execution` 的薄封装，
留给「手里已经有校验过的 Workflow」的调用方（Studio、smoke、测试）。
"""

import os
import time
from dataclasses import dataclass

from . import hooks as hooks_mod
from . import schema as schema_mod
from .errors import ExecutionError, MissingInput, ValidationFailed
from .workflow import load_workflow, validate


@dataclass
class NodeResult:
    outputs: dict
    ms: float = 0.0


class Execution:
    """一次运行的完整状态：实例、输出堆、每个节点是否最新。"""

    def __init__(self, workflow, registry, hook=None, build=True):
        self.workflow = workflow
        self.registry = registry
        self.hook = hook
        self.order = list(workflow.order)
        self.values = {}  # (节点 id, 端口) -> 真实对象，就是「程序的堆」
        self.results = {}  # 节点 id -> NodeResult（本轮输出 + 耗时）
        self.status = {node_id: "unrun" for node_id in self.order}
        self.warnings = []  # execute() 校验后填；CLI 打印 [警告] 用
        self.errors = {}  # 节点 id -> 失败原因（成功即清），全仓唯一一份
        self._instances = {}
        self._configs = {
            node_id: workflow.nodes[node_id].config for node_id in self.order
        }
        self._downstream = {node_id: set() for node_id in self.order}
        for node_id in self.order:
            for src_id, _ in workflow.nodes[node_id].inputs.values():
                self._downstream[src_id].add(node_id)
        if build:
            self._build_instances()

    def _build_instances(self):
        """建全部实例；execute() 把 on_start 插在这之前，所以留了单独入口。"""
        try:
            for node_id in self.order:
                self._build(node_id, self._configs[node_id])
        except BaseException:
            self.close()
            raise

    # -- 建实例 ----------------------------------------------------------
    def _build(self, node_id, config):
        entry = self.workflow.nodes[node_id].entry
        config = self._prepared_config(node_id, entry, config)
        self._store(node_id, self._construct(node_id, entry, config), config)

    def _rebuild(self, node_id, config):
        entry = self.workflow.nodes[node_id].entry
        config = self._prepared_config(node_id, entry, config)
        # 先建新的：构造失败就抛，旧实例 / config / status / 输出原样保留
        instance = self._construct(node_id, entry, config)
        self._close_node(node_id)
        # 换成了新参数，旧参数算出来的输出立即作废，别让下游读到错的数
        for key in [key for key in self.values if key[0] == node_id]:
            del self.values[key]
        self.results.pop(node_id, None)
        self.status[node_id] = "unrun"
        self._store(node_id, instance, config)

    def _construct(self, node_id, entry, config):
        try:
            return entry.cls(config)
        except Exception as exc:
            raise ExecutionError(
                f"节点 {node_id}（{entry.full_name}）初始化失败：{exc}",
                node_id=node_id,
            ) from exc

    def _store(self, node_id, instance, config):
        self._instances[node_id] = instance
        self._configs[node_id] = config
        if self.hook is not None:
            self.hook.emit(
                "node_create_after", {"node": node_id, "instance": instance}
            )

    def _prepared_config(self, node_id, entry, config):
        """触发 node_create_before，把钩子改过的 config 校验后返回。"""
        if self.hook is not None:
            config = self.hook.emit(
                "node_create_before", {"node": node_id, "config": config}
            )["config"]
        return self._checked_config(node_id, entry, config)

    def _checked_config(self, node_id, entry, config):
        """校验 config（未知字段要报出来）再补齐默认值。"""
        errors = schema_mod.check_config_values(
            entry.config_schema, config, f"节点 {node_id}（{entry.full_name}）.config"
        )
        if errors:
            raise ExecutionError(
                f"节点 {node_id}（{entry.full_name}）的 config 不合法："
                + "；".join(errors),
                node_id=node_id,
            )
        return schema_mod.fill_defaults(entry.config_schema, config)

    def _close_node(self, node_id):
        instance = self._instances.pop(node_id, None)
        if instance is not None:
            try:
                instance.close()
            except Exception:
                pass

    # -- 执行 ------------------------------------------------------------
    def run_node(self, node_id, config=None):
        try:
            result = self._run_node(node_id, config)
        except Exception as exc:
            if node_id in self.workflow.nodes:
                self.errors[node_id] = str(exc)
            raise
        self.errors.pop(node_id, None)
        return result

    def _run_node(self, node_id, config=None):
        node = self.workflow.nodes.get(node_id)
        if node is None:
            raise ExecutionError(f"节点 {node_id} 不存在", node_id=node_id)
        if config is not None:
            # 先按原始 config 校验（未知字段要报错），再补齐默认值跟建实例用的 config 比
            requested = self._checked_config(node_id, node.entry, config)
            if requested != self._configs[node_id]:
                self._rebuild(node_id, config)

        inputs = {}
        for port, (src_id, src_port) in node.inputs.items():
            if (src_id, src_port) in self.values:
                inputs[port] = self.values[(src_id, src_port)]
        if len(inputs) != len(node.inputs):
            raise MissingInput(_missing_text(node, self), node_id=node_id)

        if self.hook is not None:
            inputs = self.hook.emit(
                "node_invoke_before", {"node": node_id, "inputs": inputs}
            )["inputs"]
            if set(inputs) != set(node.inputs):
                raise ExecutionError(
                    f"节点 {node_id}（{node.entry.full_name}）的输入端口不匹配："
                    f"缺少 {sorted(set(node.inputs) - set(inputs))}，"
                    f"多余 {sorted(set(inputs) - set(node.inputs))}",
                    node_id=node_id,
                )

        start = time.perf_counter()
        try:
            returned = self._instances[node_id].invoke(**inputs)
        except Exception as exc:
            self.status[node_id] = "failed"
            raise ExecutionError(
                f"节点 {node_id}（{node.entry.full_name}）执行失败：{exc}",
                node_id=node_id,
            ) from exc
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        try:
            outputs = _check_output(node_id, node.entry, returned, self.registry)
            if self.hook is not None:
                outputs = self.hook.emit(
                    "node_end",
                    {"node": node_id, "outputs": outputs, "duration_ms": elapsed_ms},
                )["outputs"]
                outputs = _check_output(node_id, node.entry, outputs, self.registry)
        except ExecutionError:
            self.status[node_id] = "failed"
            raise

        for port, value in outputs.items():
            self.values[(node_id, port)] = value
        result = NodeResult(outputs=outputs, ms=elapsed_ms)
        self.results[node_id] = result
        self.status[node_id] = "fresh"
        self._mark_stale(node_id)
        return result

    def run_all(self, on_node_done=None):
        results = {}
        for node_id in self.order:
            result = self.run_node(node_id)
            results[node_id] = result
            if on_node_done is not None:
                on_node_done(node_id, result)
        return results

    def _mark_stale(self, node_id):
        """本节点重跑后，所有已经跑过的下游都过期。"""
        seen = set()
        queue = list(self._downstream[node_id])
        while queue:
            downstream = queue.pop()
            if downstream in seen:
                continue
            seen.add(downstream)
            if self.status[downstream] == "fresh":
                self.status[downstream] = "stale"
            queue.extend(self._downstream[downstream])

    def close(self):
        for node_id in list(self._instances):
            self._close_node(node_id)


def run(workflow, registry, on_node_done=None):
    execution = Execution(workflow, registry)
    try:
        return execution.run_all(on_node_done)
    finally:
        execution.close()


def execute(registry, path, cli_env=None, hook=None, on_start=None, on_node_done=None):
    """带钩子的完整驱动，返回跑完（或中止）的 Execution。"""
    cli_env = dict(cli_env or {})
    os.environ.update(cli_env)  # 钩子的 install() 也要能读到 -e 传的参数
    context = hooks_mod.load(hook) if hook is not None else None
    started = time.perf_counter()
    execution = None
    try:
        if context is not None:
            context.emit(
                "plugins_loaded",
                {
                    "plugins": sorted(registry.plugins),
                    "components": len(registry.components),
                    "types": len(registry.types),
                },
            )
        raw = load_workflow(path)
        if context is not None:
            raw = context.emit(
                "workflow_loaded", {"workflow": raw, "path": str(path)}
            )["workflow"]
        report = validate(registry, raw)
        if not report.ok:
            raise ValidationFailed(report)

        merged = dict(report.workflow.env)
        merged.update(cli_env)
        os.environ.update(merged)
        if context is not None:
            os.environ.update(context.emit("env_ready", {"env": merged})["env"])

        execution = Execution(report.workflow, registry, context, build=False)
        execution.warnings = list(report.warnings)
        if on_start is not None:
            on_start(execution)
        execution._build_instances()
        if context is not None:
            context.execution = execution
        serve = context.serve if context is not None else None
        if serve is None:
            execution.run_all(on_node_done)
        else:
            serve(execution)
    except Exception as exc:
        _emit_run_end(context, execution, started, exc)
        raise
    else:
        _emit_run_end(context, execution, started, None)
    finally:
        if execution is not None:
            execution.close()
    return execution


def _emit_run_end(context, execution, started, error):
    if context is None:
        return
    # 任一节点报过错就算失败（缺输入这类没开跑、只记 errors 的也算），
    # serve 钩子吞掉异常也不例外
    failed = error is not None or bool(execution is not None and execution.errors)
    context.emit(
        "run_end",
        {
            "status": "failed" if failed else "ok",
            "order": list(execution.order) if execution is not None else [],
            "error": None if error is None else str(error),
            "duration_ms": (time.perf_counter() - started) * 1000.0,
        },
    )


def _missing_text(node, execution):
    """9.4 的缺输入报错：逐个输入端口标出来源及是否已执行。"""
    ports = list(node.inputs.items())
    width = max(len(port) for port, _ in ports)
    lines = [f"节点 {node.id}（{node.entry.full_name}）缺少输入："]
    first_missing = None
    for port, (src_id, _) in ports:
        source = execution.workflow.nodes[src_id]
        executed = execution.status.get(src_id) in ("fresh", "stale")
        if not executed and first_missing is None:
            first_missing = src_id
        state = "已执行 ✓" if executed else "该节点尚未执行"
        lines.append(
            f"  {port:<{width}}  ← 来自 {src_id}「{source.entry.title}」，{state}"
        )
    lines.append(f"建议：先执行 {first_missing}")
    return "\n".join(lines)


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
