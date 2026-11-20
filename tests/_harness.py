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


def instantiate(registry, plugin, name, config=None):
    """按引擎的方式补默认值再实例化。

    直接调组件时必须先补默认值，否则要么 KeyError，要么测试自己手抄一份默认值、
    改产品默认值时悄无声息地脱节。
    """
    from engine.schema import fill_defaults

    entry = registry.get_component(plugin, name)
    if entry is None:
        raise AssertionError(f"组件不存在：{plugin}.{name}")
    return entry.cls(fill_defaults(entry.config_schema, config or {}))


def invoke(registry, plugin, name, config=None, **inputs):
    instance = instantiate(registry, plugin, name, config)
    try:
        return instance.invoke(**inputs)
    finally:
        instance.close()


def write_source_csv(directory, filename="data.csv"):
    """写一份最小 CSV；工作流用例的数据来源都从这里来。"""
    path = Path(directory) / filename
    path.write_text("x,y\n0,1\n1,3\n2,5\n", encoding="utf-8")
    return path


def write_demo_data(directory, filename="data.csv"):
    """regression_demo 的输入数据：y = 2x + 1 + 0.5*N(0,1)，200 行，R² 约 0.99。

    别用 3 行的迷你 CSV：20% 的测试集只剩 1 行，sklearn 的 r2 会打
    UndefinedMetricWarning 到 stderr，CLI 用例会因此误判「有错误输出」。
    """
    import numpy as np

    rng = np.random.default_rng(42)
    x = rng.uniform(0.0, 10.0, 200)
    y = 2.0 * x + 1.0 + rng.normal(0.0, 0.5, 200)
    lines = ["x,y"] + [f"{a},{b}" for a, b in zip(x, y)]
    path = Path(directory) / filename
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def source_node(directory, node_id="n1", filename="data.csv"):
    """table 类工作流的源头：写一个临时 CSV 并返回 ``fileio.LoadCSV`` 节点。

    插件层没有「造数据」组件了，要真正 run 的用例都得先落一个文件；路径用绝对路径，
    调用方就不用再为每个用例折腾 ``${workspace}``。
    """
    path = write_source_csv(directory, filename)
    return {
        "id": node_id,
        "plugin": "fileio",
        "component": "LoadCSV",
        "config": {"path": str(path)},
        "inputs": {},
    }


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
