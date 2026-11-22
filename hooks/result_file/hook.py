"""官方钩子：把整轮运行结果写成 JSON。

    python -m engine run --hook hooks/result_file -e hook_result_path=result.json <工作流>

只注册 ``run_end``；真实对象用 ``engine.preview.preview()`` 转成字符串，
因为 JSON 装不下 DataFrame。
"""

import json
import os
from pathlib import Path

from engine.preview import preview


def install(ctx):
    if not os.environ.get("hook_result_path"):
        raise RuntimeError(
            "result_file 钩子必须用 -e hook_result_path=<结果文件> 指定输出路径"
        )
    ctx.on("run_end", _write)


def _write(data, execution):
    nodes = {}
    if execution is not None:
        for node_id in execution.order:
            result = execution.results.get(node_id)
            if result is None:
                continue
            nodes[node_id] = {
                "duration_ms": round(result.ms, 1),
                "outputs": {
                    port: preview(value) for port, value in result.outputs.items()
                },
            }
    payload = {
        "status": data["status"],
        "error": data["error"],
        "order": data["order"],
        "nodes": nodes,
    }
    path = Path(os.environ["hook_result_path"])
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
