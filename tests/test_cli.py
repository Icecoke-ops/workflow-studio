"""engine.cli 命令行退出码与输出测试（同进程调用，不拉子进程）。

直接运行：python tests/test_cli.py
"""

import io
import json
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.cli import _force_utf8, main as cli_main

from _harness import check, plugin_source, run_cases, write_zip

PLUGINS = str(ROOT / "plugins")
DEMO = str(ROOT / "workflows" / "linreg_demo.json")


def call_cli(argv):
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli_main(argv)
    return code, out.getvalue(), err.getvalue()


class _RecordingStream:
    """记录 reconfigure 调用的假输出流。"""

    def __init__(self):
        self.calls = []

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)


def case_force_utf8_reconfigure():
    stream = _RecordingStream()
    _force_utf8(stream)
    check(
        stream.calls == [{"encoding": "utf-8", "errors": "replace"}],
        f"_force_utf8 应调用 reconfigure(encoding='utf-8', errors='replace')，"
        f"实际 {stream.calls}",
    )


def case_force_utf8_without_reconfigure():
    stream = io.StringIO()
    check(not hasattr(stream, "reconfigure"), "StringIO 不应该有 reconfigure 属性")
    _force_utf8(stream)  # 不抛异常即通过


def case_validate_ok():
    code, out, err = call_cli(["-p", PLUGINS, "validate", DEMO])
    check(code == 0, f"validate 好文件应 exit 0，实际 {code}；stderr：{err!r}")
    check("[校验通过]" in out, f"缺少 [校验通过]：{out!r}")
    check("n1" in out, f"输出里应包含节点 id：{out!r}")
    check(err == "", f"好文件不应输出错误：{err!r}")


def case_validate_bad():
    raw = {"name": "bad", "nodes": [{"id": "n1", "plugin": "nope", "component": "X"}]}
    with tempfile.TemporaryDirectory(prefix="engine_cli_test_") as tmp:
        bad = Path(tmp) / "bad.json"
        bad.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        code, out, err = call_cli(["-p", PLUGINS, "validate", str(bad)])
    check(code == 1, f"validate 坏文件应 exit 1，实际 {code}")
    check("[错误]" in err, f"stderr 缺少 [错误]：{err!r}")
    check("[校验失败]" in err, f"stderr 缺少 [校验失败]：{err!r}")


def case_run_ok():
    code, out, err = call_cli(["-p", PLUGINS, "run", DEMO])
    check(code == 0, f"run 好文件应 exit 0，实际 {code}；stderr：{err!r}")
    check("[开始执行]" in out, f"缺少 [开始执行]：{out!r}")
    check("[完成]" in out, f"缺少 [完成]：{out!r}")
    for node_id in ("n1", "n2", "n3", "n4"):
        check(node_id in out, f"运行输出里应包含节点 {node_id}：{out!r}")
    check(err == "", f"run 好文件不应输出错误：{err!r}")


def case_run_bad():
    raw = {"name": "bad", "nodes": [{"id": "n1", "plugin": "nope", "component": "X"}]}
    with tempfile.TemporaryDirectory(prefix="engine_cli_test_") as tmp:
        bad = Path(tmp) / "bad.json"
        bad.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        code, out, err = call_cli(["-p", PLUGINS, "run", str(bad)])
    check(code == 1, f"run 坏文件应 exit 1，实际 {code}")
    check("[校验失败]" in err, f"stderr 缺少 [校验失败]：{err!r}")


def case_missing_file():
    code, out, err = call_cli(["-p", PLUGINS, "validate", str(ROOT / "workflows" / "nope.json")])
    check(code == 1, f"不存在的文件应 exit 1，实际 {code}")
    check("[读取失败]" in err, f"stderr 缺少 [读取失败]：{err!r}")


def case_invalid_json_file():
    with tempfile.TemporaryDirectory(prefix="engine_cli_test_") as tmp:
        bad = Path(tmp) / "broken.json"
        bad.write_text("{not json", encoding="utf-8")
        code, out, err = call_cli(["-p", PLUGINS, "validate", str(bad)])
    check(code == 1, f"坏 JSON 应 exit 1，实际 {code}")
    check("[读取失败]" in err, f"stderr 缺少 [读取失败]：{err!r}")


def case_missing_plugins_dir():
    code, out, err = call_cli(["-p", str(ROOT / "no_such_plugins_dir"), "validate", DEMO])
    check(code == 0, f"插件目录不存在应 exit 0，实际 {code}")
    check("插件目录不存在" in err, f"stderr 应含目录警告：{err!r}")
    check("[校验通过]" in out, f"默认目录仍应生效：{out!r}")


def case_plugins_dir_before_after():
    with tempfile.TemporaryDirectory(prefix="engine_cli_test_") as tmp:
        root = Path(tmp)
        dir_a = root / "a"
        dir_b = root / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        write_zip(
            dir_a, "clia.zip", {"clia/__init__.py": "", "clia/components.py": plugin_source("clia")}
        )
        write_zip(
            dir_b, "clib.zip", {"clib/__init__.py": "", "clib/components.py": plugin_source("clib")}
        )
        before = call_cli(["-p", str(dir_a), "-p", str(dir_b), "plugins"])
        after = call_cli(["plugins", "-p", str(dir_a), "-p", str(dir_b)])
    check(
        before[0] == 0,
        f"-p 写在子命令前应 exit 0，实际 {before[0]}；stderr：{before[2]!r}",
    )
    check(
        after[0] == 0,
        f"-p 写在子命令后应 exit 0，实际 {after[0]}；stderr：{after[2]!r}",
    )
    check(before[1] == after[1], "两种写法的输出应一致")
    check(
        "clia" in before[1] and "clib" in before[1],
        f"两个目录的插件都应加载：{before[1]!r}",
    )


def case_plugins_command():
    code, out, err = call_cli(["-p", PLUGINS, "plugins"])
    check(code == 0, f"plugins 子命令应 exit 0，实际 {code}；stderr：{err!r}")
    for token in ("core", "linreg", "LoadCSV", "MakeLinearData"):
        check(token in out, f"输出里应包含 {token}：{out!r}")
    check("类型" in out, f"输出里应包含类型清单：{out!r}")
    check("组件" in out, f"输出里应包含组件清单：{out!r}")
    check(err == "", f"plugins 子命令不应输出错误：{err!r}")


CASES = [
    ("_force_utf8 调用 reconfigure(utf-8, replace)", case_force_utf8_reconfigure),
    ("_force_utf8 对没有 reconfigure 的流不抛异常", case_force_utf8_without_reconfigure),
    ("validate 好文件 exit 0", case_validate_ok),
    ("validate 坏文件 exit 1", case_validate_bad),
    ("run 好文件 exit 0 且输出含节点", case_run_ok),
    ("run 坏文件 exit 1", case_run_bad),
    ("不存在的文件 exit 1", case_missing_file),
    ("非法 JSON 文件 exit 1", case_invalid_json_file),
    ("插件目录不存在 exit 0 + 警告", case_missing_plugins_dir),
    ("-p 写在子命令前后输出一致", case_plugins_dir_before_after),
    ("plugins 子命令列出插件与组件", case_plugins_command),
]


def main():
    return run_cases("cli", CASES)


if __name__ == "__main__":
    sys.exit(main())
