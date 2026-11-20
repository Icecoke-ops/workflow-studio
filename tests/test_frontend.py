"""前端纯函数测试的 Node 入口：run_all.py 只收集 test_*.py，所以这里起 node 跑 .mjs。

直接运行：python tests/test_frontend.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "test_frontend.mjs"


def main():
    node = shutil.which("node")
    if node is None:
        print("前端测试需要 node")
        return 1
    # 子进程继承 stdout 直接写同一句柄；先 flush，否则父进程缓冲的标题会排在子进程输出后面。
    sys.stdout.flush()
    # 不用 PIPE：本机沙箱禁止命名管道，子进程直接继承 stdout/stderr 才不会被拒。
    completed = subprocess.run([node, str(SCRIPT)], check=False)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
