"""P2 自检：同一进程里起 StudioServer，用 urllib 打五个接口并断言。

    python tests/studio_api.py

插件临时打到系统临时目录，跑完清理，不往仓库里丢东西。
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import __version__ as ENGINE_VERSION  # noqa: E402
from engine.registry import Registry  # noqa: E402
from studio import server as server_module  # noqa: E402
from studio.contract import (  # noqa: E402
    ApiService,
    check_health,
    check_plugins,
    check_run,
    check_validate,
)
from studio.server import EngineService, StudioServer  # noqa: E402
from tools.build_plugins import build_all  # noqa: E402

DEMO = ROOT / "workflows" / "linreg_demo.json"


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[OK] {message}")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_health(base, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=1) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            time.sleep(0.1)
    return None


class Api:
    """最小 HTTP 客户端：返回 (状态码, Content-Type, 原始文本)。"""

    def __init__(self, base):
        self.base = base

    def call(self, path, payload=None, raw=None):
        data = None
        headers = {}
        if raw is not None:
            data = raw.encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as exc:
            response = exc
        body = response.read().decode("utf-8")
        return response.status, response.headers.get("Content-Type", ""), body

    def json(self, path, payload=None, raw=None):
        status, content_type, body = self.call(path, payload, raw)
        return status, content_type, json.loads(body)


def main():
    temp = Path(tempfile.mkdtemp(prefix="studio_api_"))
    server = None
    thread = None
    try:
        built = build_all(temp / "plugins")
        check(len(built) == 2, f"打包出 {len(built)} 个插件")
        registry = Registry().load(temp / "plugins")

        service = EngineService(registry)
        check(isinstance(service, ApiService), "服务实例是 ApiService 的子类")

        web = temp / "web"
        web.mkdir()
        server = StudioServer(("127.0.0.1", 0), service, web)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        api = Api(f"http://127.0.0.1:{server.server_address[1]}")

        # 1) 健康检查
        status, content_type, body = api.json("/api/health")
        check(status == 200, "GET /api/health 返回 200")
        check(content_type == "application/json; charset=utf-8", f"Content-Type = {content_type}")
        check(
            body["ok"] is True
            and body["engine"] == ENGINE_VERSION
            and body["plugins"] == 3
            and body["components"] == 6,
            f"健康检查 {body}（engine {ENGINE_VERSION}）",
        )
        check(check_health(body) == body, "health 响应通过 check_health")

        # 2) 插件列表：std 是内置类型插件，core / linreg 只出组件
        status, _, body = api.json("/api/plugins")
        plugins = {item["name"]: item for item in body["plugins"]}
        check(
            status == 200 and set(plugins) == {"std", "core", "linreg"},
            f"插件 {sorted(plugins)}",
        )
        check(check_plugins(body) == body, "plugins 响应通过 check_plugins")
        total = sum(len(item["components"]) for item in plugins.values())
        check(total == 6, f"组件数 {total}")

        std = plugins["std"]
        check(
            std["version"] == "1.0"
            and std["title"] == "标准类型"
            and std["components"] == [],
            f"std 是内置伪插件：v{std['version']} / {std['title']} / components={std['components']}",
        )
        check(len(std["types"]) == 5, f"std 带出 5 个标准类型：{[t['id'] for t in std['types']]}")
        std_types = {t["id"]: t["desc"] for t in std["types"]}
        check(
            "std_1.0@table" in std_types
            and "std_1.0@model" in std_types
            and bool(std_types["std_1.0@table"])
            and bool(std_types["std_1.0@model"]),
            f"std 类型含 table / model 且描述非空：{std_types}",
        )
        check(
            registry.plugins["std"].source == "<builtin>",
            f"std 来源 {registry.plugins['std'].source}",
        )
        fit = next(c for c in plugins["linreg"]["components"] if c["name"] == "FitLinearRegression")
        data_port = fit["input_schema"]["data"]
        check(
            data_port["types"] == ["std_1.0@table"]
            and data_port["type_labels"] == ["std@table"]
            and data_port["required"] is True
            and data_port["title"] == "训练数据",
            f"FitLinearRegression.input_schema.data = {data_port}",
        )
        model_port = fit["output_schema"]["model"]
        check(
            model_port["type"] == "std_1.0@model"
            and model_port["type_label"] == "std@model",
            f"FitLinearRegression.output_schema.model = {model_port}",
        )
        predict = next(c for c in plugins["core"]["components"] if c["name"] == "PredictModel")
        check(
            predict["input_schema"]["model"]["types"] == ["std_1.0@model"]
            and predict["input_schema"]["data"]["types"] == ["std_1.0@table"]
            and predict["output_schema"]["predictions"]["type"] == "std_1.0@table",
            "core.PredictModel 端口全部指向 std 类型",
        )
        check(
            predict["output_schema"]["predictions"]["type_label"] == "std@table",
            "core.PredictModel.predictions 的 type_label = std@table",
        )
        original = registry.components[("linreg", "FitLinearRegression")]
        check(fit["config_schema"] == original.config_schema, "config_schema 原样返回")

        raw = json.loads(DEMO.read_text(encoding="utf-8"))

        # 3) 校验通过
        status, _, body = api.json("/api/validate", {"workflow": raw})
        check(
            status == 200 and body["ok"] is True and body["errors"] == [],
            f"validate 通过，order={body['order']}",
        )
        check(body["order"] == ["n1", "n2", "n3", "n4"], "拓扑顺序 n1 -> n2 -> n3 -> n4")
        check(check_validate(body) == body, "validate 通过响应通过 check_validate")

        # 4) 校验拒绝
        bad = json.loads(json.dumps(raw))
        bad["nodes"][2]["inputs"]["model"] = {"from": "n1", "port": "data"}
        status, _, body = api.json("/api/validate", {"workflow": bad})
        joined = " | ".join(body["errors"])
        check(
            status == 200 and body["ok"] is False and "类型不匹配" in joined,
            f"validate 拒绝类型错接：{joined}",
        )
        check(body["order"] == [], "校验失败时 order 为空")
        check(check_validate(body) == body, "validate 拒绝响应通过 check_validate")

        # 5) 运行通过
        status, _, body = api.json("/api/run", {"workflow": raw})
        check(status == 200 and body["ok"] is True and body["errors"] == [], "run 执行成功")
        check(check_run(body) == body, "run 成功响应通过 check_run")
        nodes = body["nodes"]
        check([n["id"] for n in nodes] == ["n1", "n2", "n3", "n4"], f"节点顺序 {[n['id'] for n in nodes]}")
        check({n["id"] for n in nodes} == set(body["order"]), "ok=true 时 nodes 覆盖全部 order")
        check(all(n["error"] is None for n in nodes), "所有节点 error 均为 null")
        check(
            all(isinstance(n["ms"], (int, float)) and n["ms"] >= 0 for n in nodes),
            "每个节点都带毫秒耗时",
        )
        check(nodes[1]["outputs"]["model"], "n2 输出 model 预览非空")
        metrics = nodes[3]["outputs"]["metrics"]
        match = re.search(r"\br2\s+([0-9.]+)", metrics)
        check(match is not None, "n4 指标表含 r2")
        check(float(match.group(1)) > 0.95, f"r2 = {match.group(1)} > 0.95")

        # 6) 执行期异常：200 + ok:false，已完成的节点照常返回
        broken = json.loads(json.dumps(raw))
        broken["nodes"][3]["config"]["target"] = "nope"
        status, _, body = api.json("/api/run", {"workflow": broken})
        check(status == 200 and body["ok"] is False, "执行期异常返回 200 + ok:false")
        check(bool(body["errors"]), "执行失败时 errors 非空")
        check(check_run(body) == body, "run 失败响应通过 check_run")
        joined = " | ".join(body["errors"])
        check("n4" in joined and "列不存在" in joined, f"错误信息带节点与原因：{joined}")
        by_id = {n["id"]: n for n in body["nodes"]}
        check(set(by_id) == {"n1", "n2", "n3", "n4"}, f"已完成的节点仍在：{sorted(by_id)}")
        check(by_id["n1"]["error"] is None and by_id["n1"]["outputs"]["data"], "n1 结果保留")
        check(by_id["n2"]["outputs"]["model"], "n2 结果保留")
        check(by_id["n4"]["error"] is not None, "n4 标记失败原因")

        # 7) 环境变量不残留：第一次带 env，第二次不带，运行期各读一次
        os.environ["STUDIO_ENV_TEST"] = "before"
        original_run = server_module.run
        seen = []

        def spy_run(workflow_obj, registry, on_node_done=None):
            seen.append(os.environ.get("STUDIO_ENV_TEST"))
            return original_run(workflow_obj, registry, on_node_done)

        server_module.run = spy_run
        try:
            with_env = json.loads(json.dumps(raw))
            with_env["env"] = {"STUDIO_ENV_TEST": "one"}
            status, _, body = api.json("/api/run", {"workflow": with_env})
            check(status == 200 and body["ok"] is True, "带 env 的 run 成功")
            status, _, body = api.json("/api/run", {"workflow": raw})
            check(status == 200 and body["ok"] is True, "不带 env 的 run 成功")
            check(seen == ["one", "before"], f"两次运行期环境 = {seen}")
            check(
                os.environ.get("STUDIO_ENV_TEST") == "before",
                "run 结束后环境变量还原到运行前的值",
            )
        finally:
            server_module.run = original_run
            del os.environ["STUDIO_ENV_TEST"]

        # 8) web 目录为空时 GET / 给提示页
        status, content_type, body = api.call("/")
        check(status == 200 and content_type.startswith("text/html"), f"GET / 返回 HTML（{content_type}）")
        check("python tools/build_web.py" in body, "提示页含构建命令")

        # 9) 真实产物目录：静态文件能取到（含子目录），GET / 回 index.html
        (web / "sub").mkdir()
        (web / "app.js").write_text("console.log('studio');\n", encoding="utf-8")
        (web / "sub" / "x.css").write_text(".studio { color: red; }\n", encoding="utf-8")
        (web / "index.html").write_text("<h1>studio-web-ok</h1>", encoding="utf-8")
        (temp / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")

        status, content_type, body = api.call("/static/app.js")
        check(
            status == 200 and "javascript" in content_type and "charset=utf-8" in content_type,
            f"GET /static/app.js 200（{content_type}）",
        )
        check("studio" in body, "/static/app.js 内容正确")

        status, content_type, body = api.call("/static/sub/x.css")
        check(
            status == 200 and content_type.startswith("text/css") and "charset=utf-8" in content_type,
            f"GET /static/sub/x.css 200（{content_type}）",
        )
        check("color: red" in body, "/static/sub/x.css 子目录内容正确")

        # 越界访问：不能读到 web 目录外面的 secret.txt
        for path in ("/static/../secret.txt", "/static/..%2Fsecret.txt"):
            status, content_type, body = api.call(path)
            payload = json.loads(body)
            check(
                status == 404 and content_type.startswith("application/json"),
                f"GET {path} 404 JSON",
            )
            check(payload["ok"] is False and "未知路径" in payload["errors"][0], f"GET {path} 被拒绝")
            check("TOP-SECRET" not in body, f"GET {path} 没有越出 web 目录")

        status, content_type, body = api.call("/static/")
        check(
            status == 404 and content_type.startswith("application/json"),
            "GET /static/ 空路径 404 JSON",
        )
        check("Traceback" not in body, "GET /static/ 不打堆栈")

        status, content_type, body = api.call("/")
        check(
            status == 200 and content_type.startswith("text/html"),
            f"有 index.html 时 GET / 200（{content_type}）",
        )
        check(
            "studio-web-ok" in body and "python tools/build_web.py" not in body,
            "GET / 返回真实 index.html 而不是占位提示页",
        )

        # 10) 未知路径 404，也是 JSON
        status, content_type, body = api.call("/api/nope")
        check(
            status == 404
            and content_type.startswith("application/json")
            and json.loads(body)["ok"] is False,
            "未知路径 404 JSON",
        )
        status, _, body = api.call("/static/missing.js")
        check(status == 404 and json.loads(body)["ok"] is False, "缺失静态文件 404 JSON")

        # 11) 非法 JSON 请求体
        status, _, body = api.json("/api/validate", raw="not json")
        check(
            status == 400 and body == {"ok": False, "errors": ["请求体不是合法 JSON"]},
            f"非法 JSON 请求体 {body}",
        )

        # 12) 真实启动：python -m studio 走 main()，能起服务、health 正常
        port = free_port()
        process = subprocess.Popen(
            [sys.executable, "-m", "studio", "--port", str(port)],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            health = wait_health(f"http://127.0.0.1:{port}", timeout=10)
            check(health is not None, f"python -m studio --port {port} 启动成功")
            check(
                health["ok"] is True and health["plugins"] >= 1,
                f"真实进程健康检查 {health}",
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        check(process.returncode is not None, "真实进程已退出")

        print("\nALL OK")
        return 0
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
