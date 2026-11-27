"""命令行入口：``python -m engine {plugins|validate|run}``。"""

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from . import env as env_mod
from .errors import ExecutionError, HookError, RunAborted, ValidationFailed, WorkflowError
from .loader import DEFAULT_DIR
from .preview import preview
from .registry import Registry
from .runner import execute
from .workflow import load_workflow, validate


def _print_plugins(registry):
    if not registry.plugins:
        print("（没有加载到任何插件）")
        return
    for info in registry.plugins.values():
        print(f"{info.name}  v{info.version}  {info.title}")
        print(f"  dir : {info.source}")
        for short, desc in info.types.items():
            print(f"  类型 : {info.name}_{info.version}@{short}  —— {desc}")
        for (plugin, name), entry in registry.components.items():
            if plugin != info.name:
                continue
            print(f"  组件 : {name}  {entry.title}")
            if entry.desc:
                print(f"         {entry.desc}")
            for port, spec in entry.input_schema.items():
                accept = " / ".join(registry.short_type(t) for t in spec["types"])
                flag = "" if spec.get("required", True) else "（可选）"
                print(f"         入 {port}: {accept}{flag}")
            for port, spec in entry.output_schema.items():
                print(f"         出 {port}: {registry.short_type(spec['type'])}")
        print()


def _print_report(report):
    """打印校验报告，返回是否通过。"""
    for warning in report.warnings:
        print(f"[警告] {warning}")
    if report.ok:
        return True
    for error in report.errors:
        print(f"[错误] {error}", file=sys.stderr)
    print(f"[校验失败] 共 {len(report.errors)} 条错误", file=sys.stderr)
    return False


def _run_report(registry, args, cli_env, hook_path):
    if args.command == "validate":
        try:
            raw = load_workflow(args.file)
        except WorkflowError as exc:
            print(f"[读取失败] {exc}", file=sys.stderr)
            return 1
        report = validate(registry, raw)
        if not _print_report(report):
            return 1
        title = report.workflow.name or args.file
        print(f"[校验通过] {title}，{len(report.workflow.nodes)} 个节点")
        print("执行顺序：" + " -> ".join(report.workflow.order))
        return 0

    execution = None
    blocks = []

    def on_start(current):
        nonlocal execution
        execution = current
        for warning in current.warnings:
            print(f"[警告] {warning}")
        title = current.workflow.name or args.file
        print(f"[开始执行] {title}，{len(current.workflow.nodes)} 个节点")

    def on_node_done(node_id, result):
        node = execution.workflow.nodes[node_id]
        lines = [f"\n[{node_id}] {node.entry.full_name}  {result.ms:.1f} ms"]
        for port, value in result.outputs.items():
            body = preview(value).replace("\n", "\n    ")
            lines.append(f"  {port} -> {body}")
        # 失败时不打半截节点块，全部成功后才统一输出
        blocks.append("\n".join(lines))

    try:
        execute(
            registry,
            args.file,
            cli_env,
            hook_path,
            on_start=on_start,
            on_node_done=on_node_done,
        )
    except ValidationFailed as exc:
        _print_report(exc.report)
        return 1
    except (RunAborted, ExecutionError) as exc:
        print(f"[执行失败] {exc}", file=sys.stderr)
        return 1
    except HookError as exc:
        print(f"[钩子错误] {exc}", file=sys.stderr)
        return 1
    except WorkflowError as exc:
        print(f"[读取失败] {exc}", file=sys.stderr)
        return 1

    for block in blocks:
        print(block)
    print(f"\n[完成] 共 {len(execution.results)} 个节点")
    return 0


def _force_utf8(stream):
    """Windows 上输出重定向到文件时默认按 cp936 编码，中文以外的字符会裸栈崩掉。"""
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _add_common_args(parser):
    """-p / -e / --hook：写在子命令前后都要生效，所以每个 parser 都挂一份。"""
    parser.add_argument(
        "-p", "--plugins-dir", action="append", metavar="DIR",
        help="插件根目录（存放插件子目录），可重复指定；默认扫描工程 plugins/",
    )
    parser.add_argument(
        "-e", "--env", action="append", metavar="KEY=VALUE",
        help="设置环境变量，可重复指定；在工作流 env 之后覆盖，仅 run 子命令生效",
    )
    parser.add_argument(
        "--hook", action="append", metavar="PATH",
        help="执行钩子路径（目录或 .py 文件），v1 只能指定一个，仅 run 子命令生效",
    )


def main(argv=None):
    _force_utf8(sys.stdout)
    _force_utf8(sys.stderr)
    common = argparse.ArgumentParser(add_help=False)
    _add_common_args(common)
    parser = argparse.ArgumentParser(
        prog="engine",
        description=f"数据分析工作流执行引擎 v{__version__}",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plugins", parents=[common], help="列出已加载的插件、组件和类型")
    validate_parser = sub.add_parser(
        "validate", parents=[common], help="只校验工作流，不执行"
    )
    validate_parser.add_argument("file", help="工作流 JSON 文件")
    run_parser = sub.add_parser("run", parents=[common], help="校验并执行工作流")
    run_parser.add_argument("file", help="工作流 JSON 文件")
    opts, _ = common.parse_known_args(argv)
    args = parser.parse_args(argv)
    args.plugins_dir = opts.plugins_dir or []
    args.env = opts.env or []
    hook_paths = opts.hook or []
    if len(hook_paths) > 1:
        print(
            f"[钩子错误] --hook 只能指定一个，实际给了 {len(hook_paths)} 个",
            file=sys.stderr,
        )
        return 1
    hook_path = hook_paths[0] if hook_paths else None

    try:
        cli_env = env_mod.parse_pairs(args.env)
    except ValueError as exc:
        print(f"[环境变量错误] {exc}", file=sys.stderr)
        return 1

    startup_env = {
        "workspace": os.getcwd(),
        "engine_version": __version__,
        "run_id": env_mod.new_run_id(),
    }
    if getattr(args, "file", None):
        startup_env["workflow"] = str(Path(args.file).resolve())
    os.environ.update(startup_env)

    try:
        registry = Registry().load(DEFAULT_DIR, *args.plugins_dir)
    except WorkflowError as exc:
        print(f"[插件加载失败] {exc}", file=sys.stderr)
        return 1

    if args.command == "plugins":
        _print_plugins(registry)
        return 0

    return _run_report(registry, args, cli_env, hook_path)


if __name__ == "__main__":
    sys.exit(main())
