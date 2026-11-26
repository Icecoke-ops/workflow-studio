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
    """失败信封；errors 可以给单条字符串。"""
    if isinstance(errors, str):
        errors = [errors]
    return {"ok": False, "errors": list(errors), **extra}


def query_path(url, default=""):
    values = parse_qs(url.query, keep_blank_values=True).get("path")
    return default if values is None else values[0]


class StudioHTTPHandler(BaseHTTPRequestHandler):
    """共用传输管道；子类只实现 _handle_get / _handle_post / _on_error。"""

    timeout = 30
    max_body = 16 * 1024 * 1024

    def do_GET(self):
        self._dispatch(self._handle_get)

    def do_POST(self):
        self._dispatch(self._handle_post)

    def _handle_get(self):
        raise NotImplementedError

    def _handle_post(self):
        raise NotImplementedError

    def _on_error(self, exc):
        raise NotImplementedError

    def _dispatch(self, handler):
        if not self._guard():
            return
        try:
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
            self._send_json(HTTPStatus.FORBIDDEN, fail([f"Host 不被允许：{host!r}"]))
            return False
        if self.command == "POST":
            origin = self.headers.get("Origin")
            if origin is not None and origin not in [
                f"http://{item}" for item in hosts
            ]:
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
        self._send_json(HTTPStatus.NOT_FOUND, fail([f"未知路径：{path}"]))

    def _bad_request(self, message):
        self._send_json(HTTPStatus.BAD_REQUEST, fail([message]))

    def _string_field(self, payload, key):
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            self._bad_request(f"请求体缺少 {key} 字符串")
            return None
        return value

    # -- 请求 ------------------------------------------------------------
    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > self.max_body:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                fail([f"请求体超过 {self.max_body} 字节"]),
            )
            return None
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict):
            self._bad_request("请求体不是合法 JSON")
            return None
        return payload
