"""http_debug 的传输层：监听、握手校验、``POST /shutdown``、每条连接的收发。

HTTP 嗅探是自己写的，不是无谓的轮子：websockets 16.0 在 ``Request.parse``
阶段就拒掉非 GET 请求（``ValueError: unsupported HTTP method``），
``process_request`` 根本收不到 ``POST /shutdown``，只能自己在 accept 之后先看首包。
"""

import json
import os
import re
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

from websockets.exceptions import ConnectionClosed
from websockets.protocol import OPEN
from websockets.server import ServerProtocol
from websockets.sync.server import ServerConnection

from engine.errors import HookError

from .fdlog import Outbox

HOST = "127.0.0.1"
OUTBOX_LIMIT = 5000  # 每条连接的待发送上限：客户端积压时丢最旧的行
ORIGIN_RE = re.compile(r"^http://(127\.0\.0\.1|localhost):\d+$")


class Server:
    """阻塞式 WebSocket 服务；收到 ``POST /shutdown`` 后 :meth:`run` 返回。"""

    def __init__(self, port, token, port_file, on_command):
        self.port = port
        self.token = token
        self.port_file = port_file
        self.on_command = on_command
        self._lock = threading.Lock()
        self._clients = {}
        self._stop = threading.Event()
        self._listener = None

    def run(self):
        try:
            self._listener = socket.create_server((HOST, self.port))
        except OSError as exc:
            raise HookError(
                f"http_debug 钩子无法监听 {HOST}:{self.port}：{exc}"
            ) from exc
        try:
            # 绑 0 时端口由系统分配；实际端口以 getsockname 为准，立刻落盘当就绪信号
            self.port = self._listener.getsockname()[1]
            self._write_port_file()
            self._listener.settimeout(0.2)
            while not self._stop.is_set():
                try:
                    sock, _ = self._listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    # 单次瞬态错误（对端在 accept 前 RST 等）不该结束会话；
                    # 睡一下，持续错误（句柄耗尽）时也不会烧 CPU
                    time.sleep(0.05)
                    continue
                threading.Thread(
                    target=self._handle_socket, args=(sock,), daemon=True
                ).start()
        finally:
            self.close()

    def _write_port_file(self):
        """先写临时文件再原子替换：Studio 一看到文件就能读到完整端口号。"""
        staging = self.port_file + ".tmp"
        try:
            with open(staging, "w", encoding="utf-8") as handle:
                handle.write(f"{self.port}\n")
            os.replace(staging, self.port_file)
        except OSError as exc:
            try:
                os.unlink(staging)
            except OSError:
                pass
            raise HookError(
                f"http_debug 钩子无法写 hook_port_file {self.port_file}：{exc}"
            ) from exc

    def broadcast(self, payload):
        with self._lock:
            clients = list(self._clients.values())
        for client in clients:
            client.send(payload)

    def close(self):
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            client.close()
        if self._listener is not None:
            _close(self._listener)
            self._listener = None

    # -- 连接 ------------------------------------------------------------
    def _handle_socket(self, sock):
        try:
            sock.settimeout(10)
            first = sock.recv(4096, socket.MSG_PEEK)
            sock.settimeout(None)
        except OSError:
            _close(sock)
            return
        if not first:
            _close(sock)
            return
        if first.startswith(b"POST "):
            self._handle_http(sock, first)
            return

        protocol = ServerProtocol()
        websocket = ServerConnection(sock, protocol, close_timeout=5)
        try:
            websocket.handshake(
                process_request=self._check_request,
                server_header=None,
                timeout=10,
            )
        except Exception:
            _close(websocket)
            return
        if websocket.state is not OPEN:
            # token / Origin 校验没过：握手已经被拒，直接丢掉
            _close(websocket)
            return

        client = Connection(websocket, self.on_command)
        with self._lock:
            self._clients[websocket] = client
        try:
            client.run()
        except ConnectionClosed:
            pass
        finally:
            with self._lock:
                self._clients.pop(websocket, None)
            client.close()

    def _check_request(self, websocket, request):
        token = (parse_qs(urlsplit(request.path).query).get("token") or [""])[0]
        if token != self.token:
            return websocket.respond(403, "bad token\n")
        origin = request.headers.get("Origin")
        if origin is not None and not ORIGIN_RE.match(origin):
            return websocket.respond(403, "bad origin\n")
        return None

    def _handle_http(self, sock, first):
        """同一个端口上的 ``POST /shutdown``：先回 200，再让 :meth:`run` 退出。"""
        try:
            sock.settimeout(2)
            data = b""
            while b"\r\n\r\n" not in data and len(data) < 65536:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            head = (data or first).split(b"\r\n", 1)[0].decode("latin-1", "replace")
            parts = head.split(" ")
            path = parts[1] if len(parts) >= 2 else ""
            if path.split("?")[0] == "/shutdown":
                body = b"bye\n"
                status = "200 OK"
                self._stop.set()
            else:
                body = b"not found\n"
                status = "404 Not Found"
            sock.sendall(
                (
                    f"HTTP/1.1 {status}\r\n"
                    "Content-Type: text/plain; charset=utf-8\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("latin-1")
                + body
            )
        except OSError:
            pass
        finally:
            _close(sock)


class Connection:
    """一条连接：读线程收命令，单独的发送线程推消息（读线程永不被对端卡住）。"""

    def __init__(self, websocket, on_command):
        self.websocket = websocket
        self.on_command = on_command
        self._outbox = Outbox(OUTBOX_LIMIT)
        self._sender = threading.Thread(target=self._send_loop, daemon=True)
        self._sender.start()

    def run(self):
        for raw in self.websocket:
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                self.send({"type": "error", "message": "命令不是合法 JSON"})
                continue
            if not isinstance(message, dict):
                self.send({"type": "error", "message": "命令必须是 JSON 对象"})
                continue
            self.on_command(self, message)

    def send(self, payload):
        self._outbox.put(payload)

    def _send_loop(self):
        while True:
            payload = self._outbox.get()
            if payload is None:
                return
            try:
                self.websocket.send(json.dumps(payload, ensure_ascii=False))
            except Exception:
                return

    def close(self):
        self._outbox.close()
        _close(self.websocket)
        self._sender.join(timeout=2)


def _close(resource):
    try:
        resource.close()
    except Exception:
        pass

