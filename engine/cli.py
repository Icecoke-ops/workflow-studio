"""命令行入口：``python -m engine {plugins|validate|run}``。"""

import argparse
import sys

from . import __version__
from .errors import WorkflowError
from .loader import DEFAULT_DIR
from .preview import preview
from .registry import Registry
from .runner import run
from .workflow import load_workflow, validate


def _print_plugins(registry):
    if not registry.plugins:
        print("（没有加载到任何插件）")
        return
    for info in registry.plugins.values():
        print(f"{info.name}  v{info.version}  {info.title}")
        print(f"  zip : {info.source}")
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


def _run_report(registry, args):
    try:
        raw = load_workflow(args.file)
    except WorkflowError as exc:
        print(f"[读取失败] {exc}", file=sys.stderr)
        return 1

    report = validate(registry, raw)
    for warning in report.warnings:
        print(f"[警告] {warning}")
    if not report.ok:
        for error in report.errors:
            print(f"[错误] {error}", file=sys.stderr)
        print(f"[校验失败] 共 {len(report.errors)} 条错误", file=sys.stderr)
        return 1

    title = report.workflow.name or args.file
    if args.command == "validate":
        print(f"[校验通过] {title}，{len(report.workflow.nodes)} 个节点")
        print("执行顺序：" + " -> ".join(report.workflow.order))
        return 0

    print(f"[开始执行] {title}，{len(report.workflow.nodes)} 个节点")
    try:
        results = run(report.workflow, registry)
    except WorkflowError as exc:
        print(f"[执行失败] {exc}", file=sys.stderr)
        return 1

    for node_id in report.workflow.order:
        node = report.workflow.nodes[node_id]
        result = results[node_id]
        print(f"\n[{node_id}] {node.entry.full_name}  {result.ms:.1f} ms")
        for port, value in result.outputs.items():
            body = preview(value).replace("\n", "\n    ")
            print(f"  {port} -> {body}")
    print(f"\n[完成] 共 {len(results)} 个节点")
    return 0


def _force_utf8(stream):
    """Windows 上输出重定向到文件时默认按 cp936 编码，中文以外的字符会裸栈崩掉。"""
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _add_plugins_dir(parser, default):
    parser.add_argument(
        "-p",
        "--plugins-dir",
        action="append",
        default=default,
        metavar="DIR",
        help="插件 zip 目录，可重复指定；默认扫描工程 plugins/",
    )


def main(argv=None):
    _force_utf8(sys.stdout)
    _force_utf8(sys.stderr)
    parser = argparse.ArgumentParser(
        prog="engine",
        description=f"数据分析工作流执行引擎 v{__version__}",
    )
    _add_plugins_dir(parser, [])
    sub = parser.add_subparsers(dest="command", required=True)
    plugins_parser = sub.add_parser("plugins", help="列出已加载的插件、组件和类型")
    _add_plugins_dir(plugins_parser, argparse.SUPPRESS)
    validate_parser = sub.add_parser("validate", help="只校验工作流，不执行")
    validate_parser.add_argument("file", help="工作流 JSON 文件")
    _add_plugins_dir(validate_parser, argparse.SUPPRESS)
    run_parser = sub.add_parser("run", help="校验并执行工作流")
    run_parser.add_argument("file", help="工作流 JSON 文件")
    _add_plugins_dir(run_parser, argparse.SUPPRESS)

    args = parser.parse_args(argv)

    try:
        registry = Registry().load(DEFAULT_DIR, *args.plugins_dir)
    except WorkflowError as exc:
        print(f"[插件加载失败] {exc}", file=sys.stderr)
        return 1

    if args.command == "plugins":
        _print_plugins(registry)
        return 0

    return _run_report(registry, args)


if __name__ == "__main__":
    sys.exit(main())
