"""engine.cli 命令行退出码与输出测试（同进程调用，不拉子进程）。

直接运行：python tests/test_cli.py
"""

import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.cli import _force_utf8, main as cli_main

from _harness import (
    RUN_ID_RE,
    check,
    env_guard,
    get_registry,
    plugin_source,
    run_cases,
    write_demo_data,
    write_zip,
)

PLUGINS = str(ROOT / "plugins")
DEMO = str(ROOT / "workflows" / "regression_demo.json")


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
    check("n7" in out, f"输出里应包含末尾节点 id：{out!r}")
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
    # CLI 把 workspace 设成进程工作目录；demo 从那里读 data.csv、写 regression_out.csv。
    # 切到临时目录跑，先放好输入文件，别在工程根目录留东西。
    with tempfile.TemporaryDirectory(prefix="engine_cli_test_") as tmp:
        write_demo_data(tmp)
        previous = os.getcwd()
        os.chdir(tmp)
        try:
            code, out, err = call_cli(["-p", PLUGINS, "run", DEMO])
        finally:
            os.chdir(previous)
        check(
            (Path(tmp) / "regression_out.csv").is_file(),
            "SaveCSV 应把结果写到进程工作目录（${workspace}）下",
        )
    check(code == 0, f"run 好文件应 exit 0，实际 {code}；stderr：{err!r}")
    check("[开始执行]" in out, f"缺少 [开始执行]：{out!r}")
    check("[完成]" in out, f"缺少 [完成]：{out!r}")
    for node_id in ("n1", "n2", "n3", "n4", "n5", "n6", "n7"):
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


def case_plugins_dir_mixed():
    """-p 在子命令前后混写时，两边指定的目录都要参与扫描。"""
    with tempfile.TemporaryDirectory(prefix="engine_cli_test_") as tmp:
        root = Path(tmp)
        dir_a = root / "a"
        dir_b = root / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        write_zip(
            dir_a, "climixa.zip", {"climixa/__init__.py": "", "climixa/components.py": plugin_source("climixa")}
        )
        write_zip(
            dir_b, "climixb.zip", {"climixb/__init__.py": "", "climixb/components.py": plugin_source("climixb")}
        )
        code, out, err = call_cli(["-p", str(dir_a), "plugins", "-p", str(dir_b)])
    check(code == 0, f"-p 混写应 exit 0，实际 {code}；stderr：{err!r}")
    check(
        "climixa" in out and "climixb" in out,
        f"子命令前后的目录都应扫描到：{out!r}",
    )


def _env_probe_source():
    """__init__ 在 run 时执行，此时 env 已按启动值 → 工作流 → 命令行的顺序写好；
    把值打印出来，就能从 CLI 输出里读回最终生效的那一层。"""
    return plugin_source(
        "envprobe",
        class_name="EnvProbe",
        extra="import json\nimport os",
        attrs='    KEYS = ("workspace", "engine_version", "run_id", "workflow", "A", "B")',
        output_schema='{"value": {"type": "std_1.0@string"}}',
        invoke_body='return {"value": "done"}',
        init_body=(
            'print("ENVDUMP " + json.dumps('
            "{key: os.environ.get(key) for key in self.KEYS}))"
        ),
    )


def _write_env_probe(tmp):
    write_zip(
        tmp,
        "envprobe.zip",
        {"envprobe/__init__.py": "", "envprobe/components.py": _env_probe_source()},
    )


def _env_probe_workflow(tmp, name, extra=None):
    raw = {
        "name": name,
        "nodes": [
            {
                "id": "n1",
                "plugin": "envprobe",
                "component": "EnvProbe",
                "config": {},
                "inputs": {},
            }
        ],
    }
    if extra:
        raw.update(extra)
    path = Path(tmp) / f"{name}.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return path


def _read_env_dump(out):
    for line in out.splitlines():
        if line.startswith("ENVDUMP "):
            return json.loads(line[len("ENVDUMP ") :])
    raise AssertionError(f"run 输出里没有 ENVDUMP：{out!r}")


def case_env_option_before_after():
    with env_guard(), tempfile.TemporaryDirectory(prefix="engine_cli_env_") as tmp:
        _write_env_probe(tmp)
        wf = _env_probe_workflow(tmp, "envopts")
        before = call_cli(["-e", "A=1", "-e", "B=2", "-p", tmp, "run", str(wf)])
        after = call_cli(["-p", tmp, "run", str(wf), "-e", "A=1", "-e", "B=2"])
    check(
        before[0] == 0,
        f"-e 写在子命令前应 exit 0，实际 {before[0]}；stderr：{before[2]!r}",
    )
    check(
        after[0] == 0,
        f"-e 写在子命令后应 exit 0，实际 {after[0]}；stderr：{after[2]!r}",
    )
    before_env = _read_env_dump(before[1])
    after_env = _read_env_dump(after[1])
    for where, dump in (("前", before_env), ("后", after_env)):
        check(
            (dump.get("A"), dump.get("B")) == ("1", "2"),
            f"-e 写在子命令{where}没有生效：A={dump.get('A')!r} B={dump.get('B')!r}",
        )
    check(
        before_env.get("A") == after_env.get("A")
        and before_env.get("B") == after_env.get("B"),
        "两种写法解析出的环境变量应一致",
    )


def case_env_option_mixed_order():
    """-e 写在子命令前后混着来也要合并；同名时按出现顺序后者覆盖。"""
    with env_guard(), tempfile.TemporaryDirectory(prefix="engine_cli_env_") as tmp:
        _write_env_probe(tmp)
        wf = _env_probe_workflow(tmp, "envmix")
        mixed = call_cli(["-e", "A=1", "-p", tmp, "run", str(wf), "-e", "B=2"])
        ordered = call_cli(["-e", "A=1", "-p", tmp, "run", str(wf), "-e", "A=2"])
        mixed_env = _read_env_dump(mixed[1])
        ordered_env = _read_env_dump(ordered[1])
    check(mixed[0] == 0, f"混写 -e 应 exit 0，实际 {mixed[0]}；stderr：{mixed[2]!r}")
    check(
        (mixed_env.get("A"), mixed_env.get("B")) == ("1", "2"),
        f"-e 混写没合并全：A={mixed_env.get('A')!r} B={mixed_env.get('B')!r}",
    )
    check(
        ordered_env.get("A") == "2",
        f"同名 -e 应按出现顺序后者覆盖，实际 {ordered_env.get('A')!r}",
    )


def case_env_option_after_all_subcommands():
    """-e 写在 plugins / validate / run 三个子命令后面都要被接受，不能变成 exit 2。"""
    with env_guard(), tempfile.TemporaryDirectory(prefix="engine_cli_env_") as tmp:
        write_demo_data(tmp)
        previous = os.getcwd()
        os.chdir(tmp)
        try:
            plugins = call_cli(["-p", PLUGINS, "plugins", "-e", "A=1"])
            validated = call_cli(["-p", PLUGINS, "validate", "-e", "A=1", DEMO])
            executed = call_cli(["-p", PLUGINS, "run", "-e", "A=1", DEMO])
        finally:
            os.chdir(previous)
    for name, (code, out, err) in (
        ("plugins", plugins),
        ("validate", validated),
        ("run", executed),
    ):
        check(
            code == 0,
            f"{name} 子命令后写 -e 应 exit 0，实际 {code}；stderr：{err!r}",
        )
    check("core" in plugins[1], f"plugins 输出不对：{plugins[1]!r}")
    check("[校验通过]" in validated[1], f"validate 输出不对：{validated[1]!r}")
    check("[完成]" in executed[1], f"run 输出不对：{executed[1]!r}")


def case_env_option_invalid():
    code, out, err = call_cli(["-e", "A", "-p", PLUGINS, "validate", DEMO])
    check(code == 1, f"-e 缺 = 应 exit 1，实际 {code}")
    check("[环境变量错误]" in err, f"stderr 缺少 [环境变量错误]：{err!r}")
    check("'A'" in err, f"错误信息应指出非法项：{err!r}")


def case_env_priority():
    with env_guard(), tempfile.TemporaryDirectory(prefix="engine_cli_env_") as tmp:
        _write_env_probe(tmp)
        wf = _env_probe_workflow(
            tmp,
            "envpriority",
            extra={"env": {"workspace": "WORKFLOW_LEVEL", "engine_version": "WORKFLOW_LEVEL"}},
        )
        code, out, err = call_cli(
            ["-p", tmp, "-e", "workspace=CLI_LEVEL", "run", str(wf)]
        )
        dump = _read_env_dump(out)
    check(code == 0, f"run 应 exit 0，实际 {code}；stderr：{err!r}")
    for key in ("workspace", "engine_version", "run_id"):
        check(dump.get(key) is not None, f"组件初始化时 {key} 应存在：{dump!r}")
    check(
        dump.get("workspace") == "CLI_LEVEL",
        f"命令行应覆盖工作流 env，实际 {dump.get('workspace')!r}",
    )
    check(
        dump.get("engine_version") == "WORKFLOW_LEVEL",
        f"工作流 env 应覆盖启动值，实际 {dump.get('engine_version')!r}",
    )
    check(
        dump.get("workflow") == str(wf.resolve()),
        f"workflow 应是传入 JSON 的绝对路径，实际 {dump.get('workflow')!r}",
    )
    check(
        RUN_ID_RE.match(dump.get("run_id") or ""),
        f"run_id 格式应为 YYYYmmdd-HHMMSS-xxxx，实际 {dump.get('run_id')!r}",
    )


def case_plugins_command():
    code, out, err = call_cli(["-p", PLUGINS, "plugins"])
    check(code == 0, f"plugins 子命令应 exit 0，实际 {code}；stderr：{err!r}")
    for token in ("core", "fileio", "table", "split", "ml", "LoadCSV", "PredictModel"):
        check(token in out, f"输出里应包含 {token}：{out!r}")
    check("类型" in out, f"输出里应包含类型清单：{out!r}")
    check("组件" in out, f"输出里应包含组件清单：{out!r}")
    # 不断言 desc 的措辞（一句话会随文案改）：从加载器取真实 desc，验证 CLI 原样打印；
    # 端口名是结构契约，可以稳定断言。
    fill = get_registry().get_component("table", "FillMissing")
    check(fill.desc != "", "FillMissing 应声明 desc，否则这条断言没有意义")
    check(fill.desc in out, f"输出里应原样打印 FillMissing 的 desc：{fill.desc!r}")
    check("入 reference" in out, f"FillMissing 的输入端口 reference 应出现在输出：{out!r}")
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
    ("-p 在子命令前后混写两边都扫描", case_plugins_dir_mixed),
    ("-e 写在子命令前后结果一致", case_env_option_before_after),
    ("-e 混写合并且同名后者覆盖", case_env_option_mixed_order),
    ("-e 在三个子命令后都被接受", case_env_option_after_all_subcommands),
    ("-e 缺 = 时 exit 1", case_env_option_invalid),
    ("env 三级优先级：命令行 > 工作流 > 启动值", case_env_priority),
    ("plugins 子命令列出插件与组件", case_plugins_command),
]


def main():
    return run_cases("cli", CASES)


if __name__ == "__main__":
    sys.exit(main())
