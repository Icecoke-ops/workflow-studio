"""核对 docs/skill/references/api.md 与 studio 实际路由是否一致。

用法（仓库根目录）：

    python tools/check_agent_docs.py

检查三件事，任一不符都非零退出并列出明细：
1. 每个服务的**详述标题**（`### GET /api/x`）与代码路由一一对应；
2. **§一页速查**代码块里的路由与详述标题一致（只在速查里加路由会被抓）；
3. **章节标题里的计数**（「N 条路径 / M 个操作」）与实际路由数一致。
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "skill" / "references" / "api.md"

SOURCES = {
    "launcher": ROOT / "studio" / "launcher.py",
    "project": ROOT / "studio" / "server.py",
}
HANDLERS = {"_handle_get": "GET", "_handle_post": "POST"}
PATH_RE = re.compile(r"^/api/[A-Za-z0-9_/-]+$")
DOC_RE = re.compile(r"^#{1,6}\s+(GET|POST)\s+(/api/[A-Za-z0-9_/-]+)\s*$")
QUICK_RE = re.compile(r"^\s*(GET|POST)\s+(/api/[A-Za-z0-9_/-]+)")
COUNT_RE = re.compile(r"(\d+)\s*条路径\s*/\s*(\d+)\s*个操作")


def _service_of(line):
    if "launcher" in line:
        return "launcher"
    if "项目服务" in line:
        return "project"
    return None


def routes_from_code(path):
    """从 StudioHTTPHandler 子类的 _handle_get / _handle_post 里取字符串常量。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in HANDLERS:
            continue
        method = HANDLERS[node.name]
        for item in ast.walk(node):
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                if PATH_RE.match(item.value):
                    found.add((method, item.value))
    return found


def routes_from_doc(path):
    """按 api.md 的章节标题分服务，取 '### GET /api/xxx' 这类标题。"""
    found = {"launcher": set(), "project": set()}
    service = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):  # 只看二级标题切服务；端点标题是三级
            service = _service_of(line)
        if service is None:
            continue
        match = DOC_RE.match(line)
        if match:
            found[service].add((match.group(1), match.group(2)))
    return found


def routes_from_quickref(path):
    """取「一页速查」代码块里的路由，按 launcher / 项目服务 分组。"""
    found = {"launcher": set(), "project": set()}
    in_section = in_fence = False
    bucket = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_section = "一页速查" in line
            continue
        if not in_section:
            continue
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        if stripped.startswith("launcher"):
            bucket = "launcher"
            continue
        if stripped.startswith("项目服务"):
            bucket = "project"
            continue
        if stripped.startswith("调试"):
            bucket = None
            continue
        match = QUICK_RE.match(line)
        if match and bucket:
            found[bucket].add((match.group(1), match.group(2)))
    return found


def counts_from_doc(path):
    """从章节标题读声明的「N 条路径 / M 个操作」。"""
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = COUNT_RE.search(line)
        if not match:
            continue
        service = _service_of(line)
        if service:
            found[service] = (int(match.group(1)), int(match.group(2)))
    return found


def main():
    if not DOC.is_file():
        print(f"[缺少文档] {DOC}", file=sys.stderr)
        return 1

    documented = routes_from_doc(DOC)
    quickref = routes_from_quickref(DOC)
    counts = counts_from_doc(DOC)
    failed = False

    def bad(message):
        nonlocal failed
        print(f"  {message}")
        failed = True

    for service, source in sorted(SOURCES.items()):
        code = routes_from_code(source)
        docs = documented[service]
        quick = quickref[service]
        code_paths = {path for _, path in code}
        doc_paths = {path for _, path in docs}
        print(
            f"[{service}] 操作：代码 {len(code)} / 文档 {len(docs)}；"
            f"路径：代码 {len(code_paths)} / 文档 {len(doc_paths)}"
        )

        for method, path in sorted(code - docs):
            bad(f"文档漏写：{method} {path}")
        for method, path in sorted(docs - code):
            bad(f"文档多写（代码里没有）：{method} {path}")

        if not quick:
            bad("解析失败：§一页速查里没有找到该服务的路由")
        for method, path in sorted(quick - docs):
            bad(f"速查表有、详述缺：{method} {path}")
        for method, path in sorted(docs - quick):
            bad(f"详述有、速查表缺：{method} {path}")

        declared = counts.get(service)
        actual = (len(code_paths), len(code))
        if declared is None:
            bad("章节标题缺少「N 条路径 / M 个操作」计数")
        elif declared != actual:
            bad(
                f"计数不符：写 {declared[0]} 条路径 / {declared[1]} 个操作，"
                f"实际 {actual[0]} 条路径 / {actual[1]} 个操作"
            )

        if not code:
            print(f"  [解析失败] 没有从 {source.name} 取到任何路由", file=sys.stderr)
            failed = True

    if failed:
        print("[不通过] 文档与 studio 路由/计数不一致", file=sys.stderr)
        return 1
    print("[通过] 详述、速查表、计数与 studio 路由完全一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
