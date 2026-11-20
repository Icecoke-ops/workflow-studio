"""本地 Web API：给 Vue 前端提供插件查询、校验和执行接口。

    python -m studio [--plugins-dir DIR ...] [--port 8765] [--host 127.0.0.1]

分层：:class:`EngineService` 只做业务（registry -> 契约载荷），
:class:`StudioHandler` 只做 HTTP 路由/序列化/静态文件。
业务载荷形状由 :mod:`studio.contract` 的 ``check_*`` 强制。

接口：
    GET  /api/health      引擎版本与插件/组件数量
    GET  /api/plugins     插件、类型、组件及端口 schema
    POST /api/validate    校验工作流
    POST /api/run         校验并执行工作流
    GET  /                前端页面（studio/web/index.html）
    GET  /static/<file>   前端静态资源
"""

import argparse
import json
import mimetypes
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from engine import __version__ as ENGINE_VERSION
from engine.errors import WorkflowError
from engine.loader import DEFAULT_DIR
from engine.preview import preview
from engine.registry import Registry
from engine.runner import run
from engine.typeid import qualify
from engine.workflow import validate

from . import __version__
from .contract import (
    ApiService,
    check_health,
    check_plugins,
    check_run,
    check_validate,
)

__all__ = ["EngineService", "StudioServer", "main"]

WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_BODY = 16 * 1024 * 1024
HINT_TEXT = "请先运行 python tools/build_web.py 构建前端"

_JSON = "application/json; charset=utf-8"
_HTML = "text/html; charset=utf-8"


# --------------------------------------------------------------------------
# 业务层
# --------------------------------------------------------------------------

class EngineService(ApiService):
    """基于 engine 注册表的业务实现，不碰任何 HTTP 细节。"""

    def __init__(self, registry):
        self.registry = registry

    def health(self):
        registry = self.registry
        return {
            "ok": True,
            "engine": ENGINE_VERSION,
            "plugins": len(registry.plugins),
            "components": len(registry.components),
        }

    def plugins(self):
        registry = self.registry
        plugins = []
        for info in registry.plugins.values():
            components = [
                _component_payload(registry, entry)
                for (plugin, _), entry in registry.components.items()
                if plugin == info.name
            ]
            plugins.append(
                {
                    "name": info.name,
                    "version": info.version,
                    "title": info.title,
                    "types": [
                        {"id": qualify(info.name, info.version, short), "desc": str(desc)}
                        for short, desc in info.types.items()
                    ],
                    "components": components,
                }
            )
        return {"plugins": plugins}

    def validate(self, workflow):
        return _report(validate(self.registry, workflow))

    def run(self, workflow):
        report = validate(self.registry, workflow)
        payload = _report(report)
        payload["nodes"] = []
        if not report.ok:
            return payload

        workflow_obj = report.workflow
        done = {}
        try:
            run(
                workflow_obj,
                self.registry,
                on_node_done=lambda node_id, result: done.update({node_id: result}),
            )
        except WorkflowError as exc:
            message = str(exc)
            payload["ok"] = False
            payload["errors"] = [message]
            payload["nodes"] = _nodes_payload(
                workflow_obj, done, exc.node_id, message
            )
            return payload

        payload["nodes"] = _nodes_payload(workflow_obj, done, None, None)
        return payload


def _report(report):
    return {
        "ok": report.ok,
        "errors": list(report.errors),
        "warnings": list(report.warnings),
        "order": report.order,
    }


def _component_payload(registry, entry):
    return {
        "name": entry.name,
        "title": entry.title,
        "desc": entry.desc,
        "config_schema": entry.config_schema,
        "input_schema": {
            port: {
                "types": list(spec["types"]),
                "type_labels": [registry.short_type(t) for t in spec["types"]],
                "required": spec.get("required", True),
                "title": spec.get("title", ""),
                "desc": spec.get("desc", ""),
            }
            for port, spec in entry.input_schema.items()
        },
        "output_schema": {
            port: {
                "type": spec["type"],
                "type_label": registry.short_type(spec["type"]),
                "title": spec.get("title", ""),
                "desc": spec.get("desc", ""),
            }
            for port, spec in entry.output_schema.items()
        },
    }


def _nodes_payload(workflow, done, failed_id, error_message):
    nodes = []
    for node_id in workflow.order:
        node = workflow.nodes[node_id]
        item = {
            "id": node_id,
            "component": node.entry.full_name,
            "ms": 0.0,
            "outputs": {},
            "error": None,
        }
        if node_id in done:
            result = done[node_id]
            item["ms"] = round(result.ms, 2)
            item["outputs"] = _preview_outputs(result.outputs)
        elif node_id == failed_id:
            item["error"] = error_message
        else:
            continue  # 失败之后没执行的节点不返回
        nodes.append(item)
    return nodes


def _preview_outputs(outputs):
    return {port: preview(value) for port, value in outputs.items()}


# --------------------------------------------------------------------------
# 传输层
# --------------------------------------------------------------------------

class StudioServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service, web_dir=WEB_DIR):
        self.service = service
        self.web_dir = Path(web_dir).resolve()
        super().__init__(address, StudioHandler)


class StudioHandler(BaseHTTPRequestHandler):
    server_version = f"Studio/{__version__}"

    def do_GET(self):
        self._dispatch(self._handle_get)

    def do_POST(self):
        self._dispatch(self._handle_post)

    # -- 路由 ------------------------------------------------------------
    def _handle_get(self):
        path = urlsplit(self.path).path
        service = self.server.service
        if path == "/api/health":
            self._send_json(HTTPStatus.OK, check_health(service.health()))
        elif path == "/api/plugins":
            self._send_json(HTTPStatus.OK, check_plugins(service.plugins()))
        elif path == "/":
            self._serve_index()
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        else:
            self._not_found(path)

    def _handle_post(self):
        path = urlsplit(self.path).path
        if path not in ("/api/validate", "/api/run"):
            self._not_found(path)
            return

        payload = self._read_json()
        if payload is None:
            return
        workflow = payload.get("workflow")
        if not isinstance(workflow, dict):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "errors": ["请求体缺少 workflow 对象"]},
            )
            return

        service = self.server.service
        if path == "/api/validate":
            self._send_json(HTTPStatus.OK, check_validate(service.validate(workflow)))
        else:
            self._send_json(HTTPStatus.OK, check_run(service.run(workflow)))

    # -- 响应 ------------------------------------------------------------
    def _dispatch(self, handler):
        try:
            handler()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # 兜底：任何意外都回 JSON，不吐 traceback
            try:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "errors": [f"服务器内部错误：{exc}"]},
                )
            except Exception:
                pass

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_body(status, _JSON, body)

    def _send_body(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in (
            "application/javascript",
            "application/json",
            "image/svg+xml",
        ):
            ctype += "; charset=utf-8"
        self._send_body(HTTPStatus.OK, ctype, path.read_bytes())

    def _serve_index(self):
        index = self.server.web_dir / "index.html"
        if index.is_file():
            self._send_file(index)
            return
        body = (
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            "<title>前端未构建</title>"
            '<body style="font-family:system-ui,-apple-system,\'Segoe UI\',sans-serif;'
            "max-width:36em;margin:16vh auto;padding:0 1.5em;line-height:1.8;color:#1f2328\">"
            '<h1 style="font-size:1.5em">前端还没有构建</h1>'
            f"<p>{HINT_TEXT}。</p>"
            '<p>API 已经可用，可以先看 <a href="/api/health">/api/health</a>。</p>'
            "</body></html>"
        ).encode("utf-8")
        self._send_body(HTTPStatus.OK, _HTML, body)

    def _serve_static(self, rel):
        rel = unquote(rel)
        target = (self.server.web_dir / rel).resolve()
        if not target.is_relative_to(self.server.web_dir) or not target.is_file():
            self._not_found("/static/" + rel)
            return
        self._send_file(target)

    def _not_found(self, path):
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "errors": [f"未知路径：{path}"]})

    # -- 请求 ------------------------------------------------------------
    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"ok": False, "errors": [f"请求体超过 {MAX_BODY} 字节"]},
            )
            return None
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "errors": ["请求体不是合法 JSON"]},
            )
            return None
        return payload


# --------------------------------------------------------------------------
# 启动
# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="studio", description=f"数据分析工作流本地 Web API v{__version__}"
    )
    parser.add_argument(
        "-p",
        "--plugins-dir",
        action="append",
        default=None,
        help="额外插件 zip 目录，可重复指定（默认总会扫描引擎自带的 plugins/）",
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8765, help="监听端口（默认 8765）")
    args = parser.parse_args(argv)

    dirs = [DEFAULT_DIR] + (args.plugins_dir or [])
    try:
        registry = Registry().load(*dirs)
    except WorkflowError as exc:
        print(f"[插件加载失败] {exc}", file=sys.stderr)
        return 1

    try:
        server = StudioServer((args.host, args.port), EngineService(registry))
    except OSError as exc:
        print(f"[启动失败] 无法监听 {args.host}:{args.port}：{exc}", file=sys.stderr)
        return 1

    host, port = server.server_address[:2]
    print(
        f"[studio] 引擎 v{ENGINE_VERSION}，"
        f"{len(registry.plugins)} 个插件 / {len(registry.components)} 个组件",
        flush=True,
    )
    print(f"[studio] 监听 http://{host}:{port}/ （Ctrl+C 停止）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("[studio] 已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
