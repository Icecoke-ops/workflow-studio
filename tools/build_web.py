"""构建前端并拷贝到 studio/web。

    python tools/build_web.py             # npm 构建 + 拷贝
    python tools/build_web.py --no-build  # 只拷贝已有的 frontend/dist

npm 走 cmd 重定向执行（沙箱里直接 spawn 管道会 EPERM）。
"""

import argparse
import shutil
import subprocess
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

    LOG.unlink(missing_ok=True)
    command = f'npm --prefix "{FRONTEND}" run build > "{LOG}" 2>&1'
    print(f"[构建] {command}")
    # shell=True 在 Windows 上就是 cmd /c <原样命令串>；
    # 用列表传参会把内层引号转义坏，反而让 cmd 报语法错误。
    completed = subprocess.run(command, shell=True, cwd=ROOT)

    output = ""
    if LOG.is_file():
        output = LOG.read_text(encoding="utf-8", errors="replace")
        print(output.rstrip())
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
    parser = argparse.ArgumentParser(description="构建前端并拷贝到 studio/web")
    parser.add_argument("--no-build", action="store_true", help="跳过 npm build，只拷贝 dist")
    args = parser.parse_args()

    if not args.no_build:
        run_build()
    copy_dist()


if __name__ == "__main__":
    main()
