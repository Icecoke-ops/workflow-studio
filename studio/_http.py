"""两个服务共用的 HTTP 传输层：收发管道 + 回环 Host/Origin 校验。"""

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs

JSON_TYPE = "application/json; charset=utf-8"
HTML_TYPE = "text/html; charset=utf-8"


def ok(**extra):
    """成功信封。"""
    return {"ok": True, "errors": [], **extra}


def fail(errors, **extra):
    """失败信封。"""
    return {"ok": False, "errors": list(errors), **extra}


def query_path(url, default=""):
    values = parse_qs(url.query, keep_blank_values=True).get("path")
    return default if values is None else values[0]


class StudioHTTPHandler(BaseHTTPRequestHandler):
    """共用传输管道；子类只实现 _handle_get / _handle_post / _on_error。"""

    timeout = 30
    max_body = 16 * 1024 * 1024
    max_drain = 32 * 1024 * 1024  # 回错误前最多读掉这么多请求体
    _body_read = 0  # 当前请求已读掉的请求体字节数

    def do_GET(self):
        self._dispatch(self._handle_get)

    def do_POST(self):
        self._dispatch(self._handle_post)

    def handle_one_request(self):
        """对端在读请求阶段就 RST 也是正常断线，别让 socketserver 打整栈。"""
        self._body_read = 0
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _handle_get(self):
        raise NotImplementedError

    def _handle_post(self):
        raise NotImplementedError

    def _on_error(self, exc):
        raise NotImplementedError

    def _dispatch(self, handler):
        try:
            if not self._guard():
                return
            handler()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            try:
                self._on_error(exc)
            except Exception:
                pass

    # -- 安全边界 --------------------------------------------------------
    def _guard(self):
        """只接受本机回环的本端口；带 Origin 的 POST 必须同源。"""
        port = self.server.server_address[1]
        hosts = [f"127.0.0.1:{port}", f"localhost:{port}"]
        host = self.headers.get("Host")
        if host not in hosts:
            self._discard_body()
            self._send_json(HTTPStatus.FORBIDDEN, fail([f"Host 不被允许：{host!r}"]))
            return False
        if self.command == "POST":
            origin = self.headers.get("Origin")
            if origin is not None and origin not in [
                f"http://{item}" for item in hosts
            ]:
                self._discard_body()
                self._send_json(
                    HTTPStatus.FORBIDDEN, fail([f"Origin 不被允许：{origin!r}"])
                )
                return False
        return True

    # -- 响应 ------------------------------------------------------------
    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_body(status, JSON_TYPE, body)

    def _send_body(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self, path):
        self._discard_body()
        self._send_json(HTTPStatus.NOT_FOUND, fail([f"未知路径：{path}"]))

    def _bad_request(self, message):
        self._discard_body()
        self._send_json(HTTPStatus.BAD_REQUEST, fail([message]))

    def _string_field(self, payload, key):
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            self._bad_request(f"请求体缺少 {key} 字符串")
            return None
        return value

    # -- 请求 ------------------------------------------------------------
    def _content_length(self):
        try:
            return max(0, int(self.headers.get("Content-Length") or 0))
        except ValueError:
            return 0

    def _discard_body(self):
        """回错误前把没读完的请求体读掉，别让客户端还在写就被重置。

        最多再读 ``max_drain`` 字节；读不空就关连接，避免被超大声明拖住。
        """
        left = self._content_length() - self._body_read
        if left <= 0:
            return
        budget = min(left, self.max_drain)
        while budget > 0:
            chunk = self.rfile.read(min(budget, 65536))
            if not chunk:
                break
            self._body_read += len(chunk)
            budget -= len(chunk)
        if self._content_length() > self._body_read:
            self.close_connection = True

    def _read_json(self):
        length = self._content_length()
        if length > self.max_body:
            self._discard_body()
            self.close_connection = True
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                fail([f"请求体超过 {self.max_body} 字节"]),
            )
            return None
        raw = self.rfile.read(length) if length > 0 else b""
        self._body_read = len(raw)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict):
            self._bad_request("请求体不是合法 JSON")
            return None
        return payload
