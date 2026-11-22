"""官方钩子：WebSocket 调试服务，Studio 的调试器直连。

    python -m engine run --hook hooks/http_debug \
        -e hook_port_file=<端口文件> -e hook_token=<token> <工作流>

引擎启动后**不自动跑任何节点**，一切等命令。日志来自 :mod:`.fdlog`
（进程级 fd 重定向），传输与握手在 :mod:`.server`。

``hook_port`` 可选（省略或 0 由系统分配）；绑定成功后实际端口写进
``hook_port_file``，Studio 以「文件出现」为就绪信号。
"""

import os
import threading

from engine.errors import ExecutionError
from engine.preview import preview

from .fdlog import FdLog
from .server import Server

DRAIN_MAX = 0.1  # 节点切换前排空最多等这么久，空闲节点零等待

_debugger = None


def install(ctx):
    global _debugger
    port = _env_port("hook_port")
    token = os.environ.get("hook_token", "")
    if not token:
        raise RuntimeError("http_debug 钩子必须用 -e hook_token=<token> 指定访问口令")
    port_file = os.environ.get("hook_port_file", "").strip()
    if not port_file:
        raise RuntimeError(
            "http_debug 钩子必须用 -e hook_port_file=<路径> 指定端口文件"
        )
    _debugger = _Debugger(port, token, port_file)


def serve(execution):
    _debugger.serve(execution)


def _env_port(name):
    """``hook_port`` 可省略或给 0：由系统分配，实际端口写进 ``hook_port_file``。"""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} 不是整数：{raw!r}") from None
    if not 0 <= value <= 65535:
        raise RuntimeError(f"{name} 超出端口范围：{value}")
    return value


class _Debugger:
    def __init__(self, port, token, port_file):
        self.port = port
        self.token = token
        self.port_file = port_file
        self.execution = None
        self._lock = threading.Lock()
        self._busy = False
        self._abort = threading.Event()
        self._current = None
        self._log_node = None  # 日志归属：节点结束后还要留一会儿，等读线程排空尾巴
        self._phase = "idle"
        self._worker = None
        self._server = None
        self._fdlog = None

    # ---- 生命周期 ------------------------------------------------------
    def serve(self, execution):
        self.execution = execution
        self._fdlog = FdLog(self._on_log, self._log_node_of)
        self._server = Server(self.port, self.token, self.port_file, self.dispatch)
        self._fdlog.start()
        try:
            self._server.run()  # 阻塞到 POST /shutdown；close 由 Server.run 的 finally 负责
        finally:
            worker = self._worker
            if worker is not None:
                worker.join(timeout=1.5)  # 契约 9.6：最多等当前节点 1.5 秒
            self._fdlog.stop()

    # ---- 命令分发 ------------------------------------------------------
    def dispatch(self, client, message):
        name = message.get("cmd")
        with self._lock:
            busy = self._busy
        if name == "stop":
            self._abort.set()
            client.send({"type": "ack", "cmd": "stop"})
            return
        if busy:
            client.send({"type": "error", "message": "正在执行"})
            return
        if name == "state":
            client.send({"type": "state", "data": self._state()})
            return
        if name in ("run_node", "continue"):
            self._start(client, name, message)
            return
        client.send({"type": "error", "message": f"未知命令：{name!r}"})

    def _start(self, client, name, message):
        with self._lock:
            if self._busy:
                client.send({"type": "error", "message": "正在执行"})
                return
            self._busy = True
            self._phase = "running"
            self._abort.clear()
            if name == "run_node":
                node_id = message.get("id")
                self._current = node_id if isinstance(node_id, str) and node_id else None
            else:
                self._current = self._next_node(0)
        client.send({"type": "ack", "cmd": name})
        self._broadcast_state()  # 命令开始：phase=running，current 是首个要跑的节点
        worker = threading.Thread(target=self._run, args=(name, message), daemon=True)
        with self._lock:
            self._worker = worker
        worker.start()

    def _run(self, name, message):
        error = None
        try:
            if name == "run_node":
                node_id = message.get("id")
                if not isinstance(node_id, str) or not node_id:
                    raise ExecutionError("run_node 缺少 id")
                self._run_node(node_id, message.get("config"))
                self._push_state(None)
            else:
                self._run_continue()
        except ExecutionError as exc:
            error = str(exc)
        except Exception as exc:  # 钩子自己的意外错误也要回给客户端
            error = f"{type(exc).__name__}: {exc}"
        finally:
            self._sync_logs()  # 命令结束：把已经写出的尾巴排空，再清节点标签
            with self._lock:
                self._current = None
                self._log_node = None
                if error is not None:
                    self._phase = "failed"
                elif self._abort.is_set():
                    self._phase = "paused"
                elif self._all_fresh():
                    self._phase = "ended"
                else:
                    self._phase = "idle"
                self._busy = False
            if error is not None:
                self._broadcast({"type": "error", "message": error})
            self._broadcast_state()  # 命令/整轮结束

    def _run_node(self, node_id, config=None):
        self._enter_node(node_id)
        self.execution.run_node(node_id, config)

    def _run_continue(self):
        for index, node_id in enumerate(self.execution.order):
            if self._abort.is_set():
                return
            if self.execution.status.get(node_id) == "fresh":
                continue
            self._run_node(node_id)
            # 每个节点结束后立刻推一次，颜色逐个变，不用等整轮结束；
            # stop 之后不再预告下一个节点。
            self._push_state(
                None if self._abort.is_set() else self._next_node(index + 1)
            )

    def _next_node(self, start):
        """``order[start:]`` 里第一个还要跑的节点；都跑完了返回 None。"""
        for node_id in self.execution.order[start:]:
            if self.execution.status.get(node_id) != "fresh":
                return node_id
        return None

    def _all_fresh(self):
        return all(
            status == "fresh" for status in self.execution.status.values()
        )

    def _enter_node(self, node_id):
        """节点开跑：先给上一节点的日志尾巴一个有界排空窗口，再切日志归属。

        ``current`` 由 ``_start`` 与 ``_push_state`` 负责，这里不重复写。
        """
        with self._lock:
            previous = self._log_node
        if previous is not None and previous != node_id:
            self._sync_logs()
        with self._lock:
            self._log_node = node_id

    def _sync_logs(self):
        """等读线程把这个节点已经写出的日志全部发完（有界），空闲节点零等待。"""
        if self._fdlog is not None:
            self._fdlog.sync(DRAIN_MAX)

    def _push_state(self, current):
        """推一份 state 快照，并让 ``current`` 指向下一个要跑的节点。"""
        with self._lock:
            self._current = current
        self._broadcast_state()

    def _log_node_of(self):
        with self._lock:
            return self._log_node

    # ---- 推送 ----------------------------------------------------------
    def _on_log(self, node_id, stream, text):
        self._broadcast(
            {"type": "log", "node": node_id, "stream": stream, "text": text}
        )

    def _broadcast(self, payload):
        if self._server is not None:
            self._server.broadcast(payload)

    def _broadcast_state(self):
        self._broadcast({"type": "state", "data": self._state()})

    def _state(self):
        with self._lock:
            phase = self._phase
            current = self._current
        execution = self.execution
        nodes = {}
        for node_id in execution.order:
            result = execution.results.get(node_id)
            nodes[node_id] = {
                "status": execution.status.get(node_id, "unrun"),
                "duration_ms": round(result.ms, 1) if result is not None else None,
                "error": execution.errors.get(node_id),
                "outputs": (
                    {port: preview(value) for port, value in result.outputs.items()}
                    if result is not None
                    else {}
                ),
            }
        return {
            "phase": phase,
            "current": current,
            "order": list(execution.order),
            "nodes": nodes,
        }
