"""测试公共设施：断言、异常匹配、用例循环，以及临时插件 zip 夹具。

每个 test_*.py 只保留自己的用例，跑测循环统一走这里。
"""

import os
import traceback
import zipfile
from contextlib import contextmanager
from pathlib import Path


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def expect_raises(exc_type, fn, *fragments):
    try:
        fn()
    except exc_type as exc:
        text = str(exc)
        for fragment in fragments:
            check(fragment in text, f"异常信息缺少 {fragment!r}，实际：{text!r}")
        return exc
    except Exception as exc:
        raise AssertionError(
            f"期望 {exc_type.__name__}，实际 {type(exc).__name__}: {exc}"
        ) from None
    raise AssertionError(f"期望 {exc_type.__name__}，但没有抛异常")


@contextmanager
def env_guard():
    """CLI 的 run 和 -e 会直接写 os.environ 且自己不还原，
    同进程跑后续用例会读到上一轮的残值，所以这里整份快照并还原。"""
    saved = dict(os.environ)
    try:
        yield
    finally:
        for key in set(os.environ) - set(saved):
            os.environ.pop(key, None)
        for key, value in saved.items():
            if os.environ.get(key) != value:
                os.environ[key] = value


def run_cases(label, cases):
    failed = 0
    for name, fn in cases:
        try:
            fn()
        except AssertionError as exc:
            print(f"FAIL {name}: {exc}")
            failed += 1
        except Exception:
            print(f"FAIL {name}: 意外异常")
            traceback.print_exc()
            failed += 1
        else:
            print(f"ok   {name}")
    if failed:
        print(f"\n[FAIL] {label}：{failed}/{len(cases)} 个用例失败")
        return 1
    print(f"\nOK  {label}：{len(cases)} 个用例全部通过")
    return 0


def write_zip(directory, filename, entries):
    path = Path(directory) / filename
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def component_source(
    class_name,
    input_schema="{}",
    output_schema="{}",
    attrs="",
    component_name=None,
    config_body="return {}",
    invoke_body="return {}",
    with_invoke=True,
    init_body="pass",
):
    lines = [
        f"class {class_name}(Component):",
        f'    name = "{component_name or class_name}"',
    ]
    if attrs:
        lines.extend(attrs.rstrip("\n").splitlines())
    lines.extend(
        [
            "",
            "    @staticmethod",
            "    def config_schema():",
            f"        {config_body}",
            "",
            "    @staticmethod",
            "    def input_schema():",
            f"        return {input_schema}",
            "",
            "    @staticmethod",
            "    def output_schema():",
            f"        return {output_schema}",
            "",
            "    def __init__(self, config):",
            f"        {init_body}",
        ]
    )
    if with_invoke:
        lines.extend(["", "    def invoke(self):", f"        {invoke_body}"])
    return "\n".join(lines)


def plugin_source(
    name,
    *,
    version="1.0",
    title="测试插件",
    types=None,
    class_name="Thing",
    input_schema="{}",
    output_schema="{}",
    extra="",
    attrs="",
    component=None,
    components=None,
    config_body="return {}",
    invoke_body="return {}",
    with_invoke=True,
    init_body="pass",
):
    """十几段临时插件源码只差元数据和端口 schema，收成一个模板，改加载器契约只改一处。"""
    if component is None:
        component = component_source(
            class_name,
            input_schema,
            output_schema,
            attrs,
            config_body=config_body,
            invoke_body=invoke_body,
            with_invoke=with_invoke,
            init_body=init_body,
        )
    if components is None:
        components = f"COMPONENTS = [{class_name}]"
    lines = []
    if extra:
        lines.extend(extra.rstrip("\n").splitlines())
    lines.extend(
        [
            "from engine.api import Component",
            "",
            f'PLUGIN_NAME = "{name}"',
            f'PLUGIN_VERSION = "{version}"',
            f'PLUGIN_TITLE = "{title}"',
        ]
    )
    if types:
        lines.append(f"PLUGIN_TYPES = {types}")
    lines.extend(["", component.rstrip("\n"), "", components])
    return "\n".join(lines) + "\n"
