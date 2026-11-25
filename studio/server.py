"""本地 Web API：一个进程服务一个项目根。

    python -m studio --serve DIR [--port 0] [--port-file PATH] [--launcher URL] [-e KEY=VALUE ...]

只监听 127.0.0.1；插件 = 引擎自带的 plugins/ + 项目根下的 plugins/。
启动后进程工作目录切到项目根，``/api/run`` 与调试子进程里的相对路径口径一致。
分层：:class:`EngineService` 只做业务（registry / project -> 契约载荷），
:class:`StudioHandler` 只做 HTTP 路由/序列化/静态文件。
业务载荷形状由 :mod:`studio.contract` 的 ``check_*`` 强制。

接口：
    GET  /api/health      引擎版本与插件/组件数量
    GET  /api/plugins     插件、类型、组件及端口 schema
    GET  /api/project     项目根、启动参数与插件加载概况
    GET  /api/tree        列项目内一层目录（?path=）
    GET  /api/file        读项目内文本文件（?path=）
    POST /api/validate    校验工作流
    POST /api/run         校验并执行工作流
    POST /api/file        写入文本文件 {path, text}
    POST /api/mkdir       新建目录 {path}
    POST /api/rename      同目录重命名 {path, new_name}
    POST /api/delete      删除文件或空目录 {path}
    POST /api/debug/start 起调试子进程（WebSocket 由 hooks/http_debug 提供）
    POST /api/debug/stop  停止调试子进程
    GET  /                前端页面（studio/web/index.html）
    GET  /static/<file>   前端静态资源
"""

import argparse
import json
import mimetypes
import os
import sys
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from engine import __version__ as ENGINE_VERSION
from engine import env as env_mod
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
    ContractError,
    check_debug_start,
    check_debug_stop,
    check_file,
    check_health,
    check_path_result,
    check_plugins,
    check_project,
    check_run,
    check_tree,
    check_validate,
    check_write_file,
)
from .debug import DebugManager, TEMP_DIR
from .project import Project, ProjectError

__all__ = ["EngineService", "StudioServer", "main"]

WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_BODY = 16 * 1024 * 1024
HINT_TEXT = "请先运行 python tools/build_web.py 构建前端"

# 只覆盖 run；任何新接口若要临时改 os.environ，必须拿同一把锁
_RUN_LOCK = threading.Lock()

_JSON = "application/json; charset=utf-8"
_HTML = "text/html; charset=utf-8"


# ---- 业务层 ----

class EngineService(ApiService):
    """基于 engine 注册表的业务实现，不碰任何 HTTP 细节。"""

    def __init__(
        self, registry, cli_env=None, *, project, launcher=None, load_errors=()
    ):
        self.registry = registry
        self.cli_env = dict(cli_env or {})
        self._project = project
        self.launcher = launcher
        self.load_errors = list(load_errors)

    def health(self):
        registry = self.registry
        return {
            "ok": True,
            "engine": ENGINE_VERSION,
            "plugins": len(registry.plugins) if registry else 0,
            "components": len(registry.components) if registry else 0,
        }

    def plugins(self):
        if self.registry is None:
            return {"plugins": []}
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
        if self.registry is None:
            return _failed(self.load_errors)
        return _report(validate(self.registry, workflow))

    def run(self, workflow):
        if self.registry is None:
            return {**_failed(self.load_errors), "nodes": []}
        with _RUN_LOCK:
            return self._run_locked(workflow)

    def _run_locked(self, workflow):
        report = validate(self.registry, workflow)
        payload = _report(report)
        payload["nodes"] = []
        if not report.ok:
            return payload

        run_id = env_mod.new_run_id()
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        path = TEMP_DIR / f"run_{run_id}.json"
        path.write_text(json.dumps(workflow, ensure_ascii=False), encoding="utf-8")

        state = env_mod.snapshot()
        try:
            os.environ.update({"workflow": str(path), "run_id": run_id})
            env_mod.apply(report.workflow.env, self.cli_env)

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
        finally:
            env_mod.restore(state)
            path.unlink(missing_ok=True)

    # -- 项目与文件 ------------------------------------------------------
    def project(self):
        plugins = {"global": 0, "project": 0}
        skipped = []
        if self.registry is None:
            errors = list(self.load_errors)
        else:
            errors = []
            plugin_dir = self._project.root / "plugins"
            for info in self.registry.plugins.values():
                source = _plugin_source(info, plugin_dir)
                if source is not None:
                    plugins[source] += 1
            skipped = [
                {**item, "source": _skipped_source(item, plugin_dir)}
                for item in self.registry.skipped
            ]
        return check_project(
            {
                "ok": not errors,
                "root": str(self._project.root),
                "name": self._project.name,
                "launcher": self.launcher,
                "plugins": plugins,
                "skipped": skipped,
                "errors": errors,
            }
        )

    def tree(self, path):
        return check_tree(self._project.list_dir(path))

    def read_file(self, path):
        return check_file(self._project.read_text(path))

    def write_file(self, path, text):
        return check_write_file(self._project.write_text(path, text))

    def mkdir(self, path):
        return check_path_result(self._project.mkdir(path), "mkdir")

    def rename(self, path, new_name):
        return check_path_result(self._project.rename(path, new_name), "rename")

    def delete(self, path):
        return check_path_result(self._project.delete(path), "delete")


def _failed(errors):
    return {"ok": False, "errors": list(errors), "warnings": [], "order": []}


def _plugin_source(info, plugin_dir):
    """插件来自全局 plugins/ 还是项目 plugins/；内置 std 不是目录里的插件。"""
    if info.source == "<builtin>":
        return None
    return "project" if _same_dir(Path(info.source).parent, plugin_dir) else "global"


def _skipped_source(item, plugin_dir):
    return "project" if _same_dir(Path(item["path"]).parent, plugin_dir) else "global"


def _same_dir(left, right):
    key = lambda path: os.path.normcase(str(Path(path).resolve()))  # noqa: E731
    return key(left) == key(right)


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
            item["outputs"] = {
                port: preview(value) for port, value in result.outputs.items()
            }
        elif node_id == failed_id:
            item["error"] = error_message
        else:
            continue  # 失败之后没执行的节点不返回
        nodes.append(item)
    return nodes


# ---- 传输层 ----

class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows 的 SO_REUSEADDR 允许同端口重复监听；用它默认的独占行为挡住第二次启动
    allow_reuse_address = os.name != "nt"

    def __init__(self, address, service, web_dir=WEB_DIR, debug=None):
        self.service = service
        self.debug = debug if debug is not None else DebugManager()
        self.web_dir = Path(web_dir).resolve()
        super().__init__(address, StudioHandler)

    def server_close(self):
        self.debug.shutdown()
        super().server_close()


class StudioHandler(BaseHTTPRequestHandler):
    server_version = f"Studio/{__version__}"
    timeout = 30

    def do_GET(self):
        self._dispatch(self._handle_get)

    def do_POST(self):
        self._dispatch(self._handle_post)

    # -- 路由 ------------------------------------------------------------
    def _handle_get(self):
        url = urlsplit(self.path)
        path = url.path
        service = self.server.service
        if path == "/api/health":
            self._send_json(HTTPStatus.OK, check_health(service.health()))
        elif path == "/api/plugins":
            self._send_json(HTTPStatus.OK, check_plugins(service.plugins()))
        elif path == "/api/project":
            self._send_json(HTTPStatus.OK, service.project())
        elif path == "/api/tree":
            self._send_json(HTTPStatus.OK, service.tree(_query_path(url, "")))
        elif path == "/api/file":
            rel = _query_path(url, None)
            if rel is None:
                self._bad_request("缺少 path 查询参数")
                return
            self._send_json(HTTPStatus.OK, service.read_file(rel))
        elif path == "/":
            self._serve_index()
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        else:
            self._not_found(path)

    def _handle_post(self):
        path = urlsplit(self.path).path
        if path not in (
            "/api/validate",
            "/api/run",
            "/api/debug/start",
            "/api/debug/stop",
            "/api/file",
            "/api/mkdir",
            "/api/rename",
            "/api/delete",
        ):
            self._not_found(path)
            return

        payload = self._read_json()
        if payload is None:
            return
        service = self.server.service

        if path == "/api/file":
            rel = self._string_field(payload, "path")
            if rel is None:
                return
            text = payload.get("text")
            if not isinstance(text, str):
                self._bad_request("请求体缺少 text 字符串")
                return
            self._send_json(HTTPStatus.OK, service.write_file(rel, text))
            return

        if path == "/api/mkdir":
            rel = self._string_field(payload, "path")
            if rel is None:
                return
            self._send_json(HTTPStatus.OK, service.mkdir(rel))
            return

        if path == "/api/rename":
            rel = self._string_field(payload, "path")
            if rel is None:
                return
            new_name = self._string_field(payload, "new_name")
            if new_name is None:
                return
            self._send_json(HTTPStatus.OK, service.rename(rel, new_name))
            return

        if path == "/api/delete":
            rel = self._string_field(payload, "path")
            if rel is None:
                return
            self._send_json(HTTPStatus.OK, service.delete(rel))
            return

        if path == "/api/debug/stop":
            session = self._string_field(payload, "session")
            if session is None:
                return
            self._send_json(
                HTTPStatus.OK, check_debug_stop(self.server.debug.stop(session))
            )
            return

        workflow = payload.get("workflow")
        if not isinstance(workflow, dict):
            self._bad_request("请求体缺少 workflow 对象")
            return

        if path == "/api/debug/start":
            self._send_json(
                HTTPStatus.OK, check_debug_start(self.server.debug.start(workflow))
            )
            return

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
        except ProjectError as exc:
            try:
                self._send_json(
                    HTTPStatus.OK, {"ok": False, "errors": [str(exc)]}
                )
            except Exception:
                pass
        except ContractError as exc:
            try:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "errors": [str(exc)]},
                )
            except Exception:
                pass
        except Exception:
            traceback.print_exc()
            try:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "errors": ["服务器内部错误"]},
                )
            except Exception:
                pass

    def _bad_request(self, message):
        self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "errors": [message]})

    def _string_field(self, payload, key):
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            self._bad_request(f"请求体缺少 {key} 字符串")
            return None
        return value

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


# ---- 启动 ----

def _query_path(url, default):
    values = parse_qs(url.query, keep_blank_values=True).get("path")
    return default if values is None else values[0]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="studio", description=f"数据分析工作流本地 Web API v{__version__}"
    )
    parser.add_argument(
        "--serve",
        required=True,
        metavar="DIR",
        help="项目根目录（一个进程只服务一个项目，只监听 127.0.0.1）",
    )
    parser.add_argument(
        "--port", type=int, default=0, help="监听端口（默认 0，随机分配）"
    )
    parser.add_argument(
        "--port-file",
        default=None,
        metavar="PATH",
        help="绑定成功后把实际端口写进该文件，退出时删掉",
    )
    parser.add_argument(
        "--launcher",
        default=None,
        metavar="URL",
        help="落地页地址（可选，原样回给前端）",
    )
    parser.add_argument(
        "-e",
        "--env",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="注入环境变量，可重复指定（优先级高于工作流 env）",
    )
    args = parser.parse_args(argv)

    try:
        cli_env = env_mod.parse_pairs(args.env or [])
    except ValueError as exc:
        print(f"[环境变量不合法] {exc}", file=sys.stderr)
        return 1

    try:
        project = Project(args.serve)
    except ProjectError as exc:
        print(f"[项目不可用] {exc}", file=sys.stderr)
        return 1
    # --port-file 相对启动目录：chdir 之前先定死绝对路径
    port_file = Path(args.port_file).resolve() if args.port_file else None
    # 进程 cwd 就是项目根：/api/run 与调试子进程里的相对路径落到同一个地方
    try:
        os.chdir(project.root)
    except OSError as exc:
        print(f"[项目不可用] 无法进入项目目录 {project.root}：{exc}", file=sys.stderr)
        return 1
    os.environ.update(
        {"workspace": str(project.root), "engine_version": ENGINE_VERSION}
    )

    plugin_dir = project.root / "plugins"
    dirs = [DEFAULT_DIR] + ([plugin_dir] if plugin_dir.is_dir() else [])
    try:
        registry = Registry().load(*dirs, strict=False)
        load_errors = []
    except WorkflowError as exc:
        registry = None
        load_errors = [str(exc)]

    passthrough = []
    if plugin_dir.is_dir():
        passthrough += ["--plugins-dir", str(plugin_dir)]
    for pair in args.env or []:
        passthrough += ["-e", pair]
    debug = DebugManager(extra_args=passthrough, workspace=str(project.root))

    try:
        server = StudioServer(
            ("127.0.0.1", args.port),
            EngineService(
                registry,
                cli_env,
                project=project,
                launcher=args.launcher,
                load_errors=load_errors,
            ),
            debug=debug,
        )
    except OSError as exc:
        print(f"[启动失败] 无法监听 127.0.0.1:{args.port}：{exc}", file=sys.stderr)
        return 1

    _, port = server.server_address[:2]
    if port_file is not None:
        try:
            port_file.write_text(f"{port}\n", encoding="utf-8")
        except OSError as exc:
            print(f"[端口文件写入失败] {port_file}：{exc}", file=sys.stderr)
            server.server_close()
            try:
                port_file.unlink(missing_ok=True)
            except OSError:
                pass
            return 1

    if registry is None:
        print(f"[studio] 插件加载失败：{load_errors[0]}", file=sys.stderr, flush=True)
    else:
        print(
            f"[studio] 引擎 v{ENGINE_VERSION}，"
            f"{len(registry.plugins)} 个插件 / {len(registry.components)} 个组件",
            flush=True,
        )
    print(
        f"[studio] 项目 {project.root} → http://127.0.0.1:{port}/ （Ctrl+C 停止）",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if port_file is not None:
            try:
                port_file.unlink(missing_ok=True)
            except OSError:
                pass
    print("[studio] 已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
