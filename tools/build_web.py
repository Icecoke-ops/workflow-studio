"""构建前端并拷贝到 studio/web。

    python tools/build_web.py             # npm 构建 + 拷贝
    python tools/build_web.py --no-build  # 只拷贝已有的 frontend/dist

npm 用参数列表直接执行，输出重定向到日志文件（沙箱禁止管道捕获）。
Windows 上 shutil.which("npm") 拿到的是无扩展名脚本，优先取 npm.cmd。
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"
WEB = ROOT / "studio" / "web"
LOG = Path(tempfile.gettempdir()) / "workflow_studio_build.log"


def run_build():
    package_json = FRONTEND / "package.json"
    if not package_json.is_file():
        raise SystemExit(f"找不到 {package_json}")

    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise SystemExit("找不到 npm，确认 Node.js 已安装并在 PATH 中")

    command = [npm, "--prefix", str(FRONTEND), "run", "build"]
    print(f"[构建] {subprocess.list2cmdline(command)}  (日志：{LOG})")
    with LOG.open("w", encoding="utf-8", errors="replace") as log_file:
        completed = subprocess.run(command, cwd=ROOT, stdout=log_file, stderr=subprocess.STDOUT)

    print(LOG.read_text(encoding="utf-8", errors="replace").rstrip())
    if completed.returncode != 0:
        raise SystemExit(f"[构建失败] npm 退出码 {completed.returncode}，完整日志：{LOG}")


def copy_dist():
    if not (DIST / "index.html").is_file():
        raise SystemExit(f"找不到构建产物 {DIST / 'index.html'}，先跑一次构建")
    if WEB.exists():
        shutil.rmtree(WEB)
    WEB.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(DIST, WEB)

    files = [path for path in WEB.rglob("*") if path.is_file()]
    total = sum(path.stat().st_size for path in files)
    print(f"[拷贝] {DIST} -> {WEB}")
    print(f"[完成] {len(files)} 个文件，{total / 1024:.1f} KB")


def main():
    # npm 日志里有 ✓ 之类的字符，重定向到文件时默认 cp936 编码会裸栈崩掉
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="构建前端并拷贝到 studio/web")
    parser.add_argument("--no-build", action="store_true", help="跳过 npm build，只拷贝 dist")
    args = parser.parse_args()

    if not args.no_build:
        run_build()
    copy_dist()


if __name__ == "__main__":
    main()
