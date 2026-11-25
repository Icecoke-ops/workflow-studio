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
import traceback
from urllib.parse import parse_qs, urlsplit

from engine.errors import HookError

from .fdlog import Outbox

_WEBSOCKETS_MAJOR = 16


def _require_websockets(version):
    """版本或底层接口不符时的明确报错（裸 ImportError/AttributeError 不算）。"""
    return (
        f"http_debug 需要 websockets {_WEBSOCKETS_MAJOR}.x"
        f"（实测 16.0），当前 {version or '未知'}；"
        "请 pip install -r requirements.txt"
    )


try:
    import websockets
except ImportError as exc:
    raise HookError(_require_websockets("未安装")) from exc

_WEBSOCKETS_VERSION = str(getattr(websockets, "__version__", "")).strip()
if _WEBSOCKETS_VERSION.split(".", 1)[0] != str(_WEBSOCKETS_MAJOR):
    raise HookError(_require_websockets(_WEBSOCKETS_VERSION))

# 16.x 的底层 API；旧版是 accept()/reject()，没有 handshake()/respond()
try:
    from websockets.datastructures import MultipleValuesError
    from websockets.exceptions import ConnectionClosed, InvalidHandshake
    from websockets.protocol import OPEN
    from websockets.server import ServerProtocol
    from websockets.sync.server import ServerConnection
except (AttributeError, ImportError) as exc:
    raise HookError(_require_websockets(_WEBSOCKETS_VERSION)) from exc

if not (
    callable(getattr(ServerConnection, "handshake", None))
    and callable(getattr(ServerConnection, "respond", None))
):
    raise HookError(_require_websockets(_WEBSOCKETS_VERSION))

HOST = "127.0.0.1"
OUTBOX_LIMIT = 5000  # 每条连接的待发送上限：客户端积压时丢最旧的行
ORIGIN_RE = re.compile(r"^http://(127\.0\.0\.1|localhost):\d+$")
_REQUEST_LINE_RE = re.compile(rb"GET [^ ]* HTTP/1\.1")
_HEADER_NAME_RE = re.compile(rb"[-!#$%&'*+.^_`|~0-9A-Za-z]+")
_HEADER_VALUE_RE = re.compile(rb"[\x09\x20-\x7e\x80-\xff]*")


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
        split = first.split(b"\r\n\r\n", 1)
        if len(split) == 2 and not _valid_http_head(split[0]):
            # 库遇到解析不了的报文会先 send_eof 半关写端，事后再补包必失败，所以完整报文头
            # 一到就先回 400。预检只覆盖语法，且要求报文头在一次 4096 字节读取内完整到达；
            # 超过 4096、分包到达，以及语义非法（129 个头、Transfer-Encoding、非零/重复
            # Content-Length）仍走库的静默半关，这里不重复做语义校验。
            _respond(sock, "400 Bad Request", b"bad request\n")
            _close_after_write(sock)
            return

        protocol = ServerProtocol()
        websocket = ServerConnection(sock, protocol, close_timeout=5)
        try:
            websocket.handshake(
                process_request=self._check_request,
                server_header=None,
                timeout=10,
            )
        except (ConnectionClosed, OSError):
            # 对端已断/没等到请求：没有可回响应的连接
            _close_after_write(sock)
            return
        except Exception as exc:
            if not isinstance(exc, InvalidHandshake):
                # 意料之外的异常不能静默：打印到 fd 2，Studio 的子进程 stderr / 日志会带出
                traceback.print_exc()
                _close(websocket)
                return
        if websocket.state is not OPEN:
            # 握手期被拒（token/Origin/协议头/报文解析）：能发的响应库已发完，状态没进 OPEN
            _close_after_write(sock)
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
        try:
            origin = request.headers.get("Origin")
        except MultipleValuesError:
            # 重复 Origin：按坏 Origin 处理，不要让它变成库的 500 + traceback
            return websocket.respond(403, "bad origin\n")
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
            _respond(sock, status, body)
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


def _valid_http_head(head):
    """完整报文头是否是 websockets 自己能解析的 GET 升级请求；语法按库的解析口径写。"""
    lines = head.split(b"\r\n")
    if _REQUEST_LINE_RE.fullmatch(lines[0]) is None:
        return False
    for line in lines[1:]:
        name, sep, value = line.partition(b":")
        if not sep or _HEADER_NAME_RE.fullmatch(name) is None:
            return False
        if _HEADER_VALUE_RE.fullmatch(value.strip(b" \t")) is None:
            return False
    return True


def _respond(sock, status, body):
    """回一条最小 HTTP 响应；正文与 Content-Length 逐字节对应。"""
    try:
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


def _close_after_write(sock):
    """先半关写端再 close：避免未读数据让 close 变成 RST，把已写出的响应吃掉。"""
    try:
        sock.shutdown(socket.SHUT_WR)
    except OSError:
        pass
    _close(sock)

