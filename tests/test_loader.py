"""engine.loader 插件 zip 加载校验测试。

临时插件 zip 全部在系统临时目录现打现删，不动 plugins/。

直接运行：python tests/test_loader.py
"""

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.api import PredictorModel
from engine.errors import PluginLoadError, SchemaError
from engine.loader import find_zips, load_plugin
from engine.registry import Registry
from engine.workflow import validate

from _harness import check, expect_raises, run_cases


def write_zip(directory, filename, entries):
    path = Path(directory) / filename
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def _component_source(
    class_name,
    input_schema="{}",
    output_schema="{}",
    attrs="",
    component_name=None,
    config_body="return {}",
    with_invoke=True,
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
            "        pass",
        ]
    )
    if with_invoke:
        lines.extend(["", "    def invoke(self):", "        return {}"])
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
    with_invoke=True,
):
    """十几段临时插件源码只差元数据和端口 schema，收成一个模板，改加载器契约只改一处。"""
    if component is None:
        component = _component_source(
            class_name,
            input_schema,
            output_schema,
            attrs,
            config_body=config_body,
            with_invoke=with_invoke,
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


def plugin_files(package, name=None, version="1.0"):
    return {
        f"{package}/__init__.py": "",
        f"{package}/components.py": plugin_source(
            name if name is not None else package, version=version
        ),
    }


def case_good_plugin_loads():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        zip_path = write_zip(tmp, "ldp0.zip", plugin_files("ldp0"))
        check(find_zips(tmp) == [zip_path], f"find_zips 结果不对：{find_zips(tmp)}")
        info = load_plugin(zip_path, set())
        check(info.name == "ldp0", f"插件名不对：{info.name!r}")
        check(info.version == "1.0", f"版本不对：{info.version!r}")
        check(info.title == "测试插件", f"标题不对：{info.title!r}")
        check(info.types == {}, f"types 应为空：{info.types}")
        check(len(info.components) == 1, f"组件数量不对：{info.components}")


def case_real_plugins_load():
    core = load_plugin(ROOT / "plugins" / "core.zip", set())
    check(core.name == "core", f"core.zip 插件名不对：{core.name!r}")
    check(core.version == "1.0", f"core.zip 版本不对：{core.version!r}")
    check(len(core.components) == 3, f"core 应有 3 个组件：{core.components}")

    linreg = load_plugin(ROOT / "plugins" / "linreg.zip", set())
    check(linreg.name == "linreg", f"linreg.zip 插件名不对：{linreg.name!r}")
    check(len(linreg.components) == 3, f"linreg 应有 3 个组件：{linreg.components}")

    registry = Registry().load(ROOT / "plugins")
    check(
        "std_1.0@table" in registry.types,
        f"标准类型应内置：{sorted(registry.types)}",
    )
    check("std_1.0@model" in registry.types, "std_1.0@model 应内置")
    check(
        sorted(registry.plugins) == ["core", "linreg", "std"],
        f"插件集合应含内置 std：{sorted(registry.plugins)}",
    )


def case_missing_init():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        entries = {"ldp1/components.py": plugin_source("ldp1")}
        zip_path = write_zip(tmp, "ldp1.zip", entries)
        expect_raises(PluginLoadError, lambda: load_plugin(zip_path, set()), "缺少 __init__.py")


def case_two_top_dirs():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        entries = {
            "ldp2a/__init__.py": "",
            "ldp2a/components.py": plugin_source("ldp2a"),
            "ldp2b/__init__.py": "",
            "ldp2b/extra.py": "",
        }
        zip_path = write_zip(tmp, "ldp2.zip", entries)
        expect_raises(
            PluginLoadError, lambda: load_plugin(zip_path, set()), "顶层必须恰好一个插件目录"
        )


def case_no_subdirectory():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        zip_path = write_zip(tmp, "ldp3.zip", {"ldp3.py": ""})
        expect_raises(
            PluginLoadError, lambda: load_plugin(zip_path, set()), "顶层必须恰好一个插件目录"
        )


def case_missing_components_py():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        zip_path = write_zip(tmp, "ldp4.zip", {"ldp4/__init__.py": ""})
        expect_raises(
            PluginLoadError, lambda: load_plugin(zip_path, set()), "缺少 ldp4/components.py"
        )


def case_root_level_py():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        entries = plugin_files("ldp5")
        entries["stray.py"] = ""
        zip_path = write_zip(tmp, "ldp5.zip", entries)
        expect_raises(PluginLoadError, lambda: load_plugin(zip_path, set()), "源文件必须放在")


def case_plugin_name_missing():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = "from engine.api import Component\n\nPLUGIN_VERSION = \"1.0\"\n"
        zip_path = write_zip(
            tmp,
            "ldp6.zip",
            {"ldp6/__init__.py": "", "ldp6/components.py": source},
        )
        expect_raises(
            PluginLoadError, lambda: load_plugin(zip_path, set()), "PLUGIN_NAME 缺失或不合法"
        )


def case_plugin_name_mismatch():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        zip_path = write_zip(tmp, "ldp7.zip", plugin_files("ldp7", name="other"))
        expect_raises(
            PluginLoadError,
            lambda: load_plugin(zip_path, set()),
            "必须与 zip 内目录名",
        )


def case_plugin_version_invalid():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        zip_path = write_zip(tmp, "ldp8.zip", plugin_files("ldp8", version="1"))
        expect_raises(
            PluginLoadError, lambda: load_plugin(zip_path, set()), "PLUGIN_VERSION 缺失或不合法"
        )


def case_components_empty():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = plugin_source("ldp9", component="", components="COMPONENTS = []")
        zip_path = write_zip(
            tmp, "ldp9.zip", {"ldp9/__init__.py": "", "ldp9/components.py": source}
        )
        expect_raises(
            PluginLoadError, lambda: load_plugin(zip_path, set()), "COMPONENTS 必须是非空列表"
        )


def case_component_not_subclass():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = plugin_source(
            "ldp10",
            component='class NotComponent:\n    name = "Nope"',
            components="COMPONENTS = [NotComponent]",
        )
        zip_path = write_zip(
            tmp, "ldp10.zip", {"ldp10/__init__.py": "", "ldp10/components.py": source}
        )
        expect_raises(
            PluginLoadError,
            lambda: Registry().load(tmp),
            "不是 engine.api.Component 的子类",
        )


def case_duplicate_component_name():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = plugin_source(
            "ldp11",
            component=_component_source("A", component_name="Same")
            + '\n\n\nclass B(A):\n    name = "Same"',
            components="COMPONENTS = [A, B]",
        )
        zip_path = write_zip(
            tmp, "ldp11.zip", {"ldp11/__init__.py": "", "ldp11/components.py": source}
        )
        expect_raises(PluginLoadError, lambda: Registry().load(tmp), "组件名重复")


def case_duplicate_plugin_name():
    """同名插件放在两个目录里，先加载一个再加载另一个，第二次必须报重复。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        root = Path(tmp)
        first_dir = root / "a"
        second_dir = root / "b"
        first_dir.mkdir()
        second_dir.mkdir()
        write_zip(first_dir, "ldp12.zip", plugin_files("ldp12"))
        write_zip(second_dir, "ldp12.zip", plugin_files("ldp12"))
        registry = Registry()
        registry.load(first_dir)
        expect_raises(
            PluginLoadError, lambda: registry.load(second_dir), "插件名重复"
        )


def case_missing_requirement():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        entries = plugin_files("ldp13")
        entries["ldp13/requirements.txt"] = "definitely_missing_pkg_xyz>=1.0\n"
        zip_path = write_zip(tmp, "ldp13.zip", entries)
        exc = expect_raises(
            PluginLoadError, lambda: load_plugin(zip_path, set()), "pip install"
        )
        check(
            "definitely_missing_pkg_xyz" in str(exc),
            f"错误信息里应包含缺失的包名，实际：{exc}",
        )


def case_installed_requirement_ok():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        entries = plugin_files("ldp14")
        entries["ldp14/requirements.txt"] = "pandas\n"
        zip_path = write_zip(tmp, "ldp14.zip", entries)
        info = load_plugin(zip_path, set())
        check(info.name == "ldp14", "已安装依赖时不应该报错")


def case_bad_declared_type_name():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        entries = plugin_files("ldp15")
        entries["ldp15/components.py"] += '\nPLUGIN_TYPES = {"1bad": "x"}\n'
        zip_path = write_zip(tmp, "ldp15.zip", entries)
        expect_raises(PluginLoadError, lambda: load_plugin(zip_path, set()), "类型名")


def case_unregistered_output_type():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = plugin_source("ldp16", output_schema='{"out": {"type": "nosuch"}}')
        write_zip(tmp, "ldp16.zip", {"ldp16/__init__.py": "", "ldp16/components.py": source})
        expect_raises(SchemaError, lambda: Registry().load(tmp), "未注册")


def case_short_type_of_other_plugin_hint():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        provider = plugin_source("ldp17a", types='{"table": "表"}')
        consumer = plugin_source(
            "ldp17b", class_name="Consumer", input_schema='{"data": {"types": ["table"]}}'
        )
        write_zip(
            tmp, "ldp17a.zip", {"ldp17a/__init__.py": "", "ldp17a/components.py": provider}
        )
        write_zip(
            tmp, "ldp17b.zip", {"ldp17b/__init__.py": "", "ldp17b/components.py": consumer}
        )
        expect_raises(
            SchemaError, lambda: Registry().load(tmp), "未注册", "ldp17a_1.0@table"
        )


def case_types_py_broken_import():
    """types.py 自己的 import 写错必须报 PluginLoadError，不能当成没有 types.py。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        entries = plugin_files("ldp18")
        entries["ldp18/types.py"] = "import definitely_missing_module_xyz\n\nTYPES = {}\n"
        zip_path = write_zip(tmp, "ldp18.zip", entries)
        expect_raises(
            PluginLoadError,
            lambda: load_plugin(zip_path, set()),
            "types.py",
            "definitely_missing_module_xyz",
        )


def case_zip_name_mismatch():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        zip_path = write_zip(tmp, "wrong_name.zip", plugin_files("ldp19"))
        expect_raises(
            PluginLoadError,
            lambda: load_plugin(zip_path, set()),
            "文件名主干必须是插件名",
        )


def case_abstract_component_rejected_at_load():
    """缺 invoke 的组件类在加载时就该被拒，registry 里不会出现它。"""
    source = plugin_source("ldp20", class_name="NoInvoke", with_invoke=False)
    registry = Registry()
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_zip(
            tmp, "ldp20.zip", {"ldp20/__init__.py": "", "ldp20/components.py": source}
        )
        exc = expect_raises(
            PluginLoadError, lambda: registry.load(tmp), "未实现的抽象方法"
        )
        check("invoke" in str(exc), f"错误信息应指出缺 invoke：{exc}")
    check(registry.components == {}, f"抽象组件不应被注册：{registry.components}")


def case_types_py_syntax_error():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        entries = plugin_files("ldp21")
        entries["ldp21/types.py"] = "def broken(\n"
        zip_path = write_zip(tmp, "ldp21.zip", entries)
        expect_raises(PluginLoadError, lambda: load_plugin(zip_path, set()), "types.py")


def case_schema_method_raises():
    """组件 schema 方法抛非 WorkflowError 时，包装成 PluginLoadError。"""
    source = plugin_source(
        "ldp22",
        class_name="BoomSchema",
        config_body='raise RuntimeError("schema 读炸了")',
    )
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_zip(
            tmp, "ldp22.zip", {"ldp22/__init__.py": "", "ldp22/components.py": source}
        )
        expect_raises(
            PluginLoadError,
            lambda: Registry().load(tmp),
            "读取 schema 失败",
            "schema 读炸了",
        )


def case_macos_junk_ignored():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        entries = plugin_files("ldp23")
        entries["__MACOSX/ldp23/._components.py"] = "junk"
        entries["ldp23/._components.py"] = "junk"
        zip_path = write_zip(tmp, "ldp23.zip", entries)
        info = load_plugin(zip_path, set())
        check(info.name == "ldp23", "带 __MACOSX / ._ 垃圾文件的 zip 应正常加载")


def case_std_builtin():
    """标准类型不依赖任何插件，永远可用，std 是伪插件。"""
    registry = Registry().load(ROOT / "plugins")
    std = registry.plugins["std"]
    check(std.source == "<builtin>", f"std 来源应为 <builtin>：{std.source!r}")
    check(std.components == [], f"std 是伪插件，不应有组件：{std.components}")
    expected = {
        "std_1.0@table",
        "std_1.0@number",
        "std_1.0@string",
        "std_1.0@boolean",
        "std_1.0@model",
    }
    missing = expected - set(registry.types)
    check(not missing, f"标准类型不全：{sorted(missing)}")
    check(
        registry.models.get("std_1.0@model") is PredictorModel,
        f"std_1.0@model 应绑定 PredictorModel：{registry.models}",
    )


def case_std_namespace_rejected():
    """std 是保留命名空间，插件包名不能叫 std。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = plugin_source("std")
        write_zip(tmp, "std.zip", {"std/__init__.py": "", "std/components.py": source})
        expect_raises(
            PluginLoadError,
            lambda: load_plugin(Path(tmp) / "std.zip", set()),
            "保留的命名空间",
        )


def case_predictor_model_contract():
    """PredictorModel 是 ABC，predict 是抽象方法。"""
    check(
        PredictorModel.__abstractmethods__ == frozenset({"predict"}),
        f"PredictorModel 的抽象方法应只有 predict：{PredictorModel.__abstractmethods__}",
    )
    try:
        PredictorModel()
    except TypeError as exc:
        check("predict" in str(exc), f"TypeError 应提到 predict：{exc}")
    else:
        raise AssertionError("PredictorModel 不应该能直接实例化")

    class Incomplete(PredictorModel):
        pass

    try:
        Incomplete()
    except TypeError as exc:
        check("predict" in str(exc), f"缺 predict 的模型构造应 TypeError：{exc}")
    else:
        raise AssertionError("继承但没实现 predict 的模型不应能实例化")

    class Complete(PredictorModel):
        def predict(self, frame):
            return [0.0] * len(frame)

    check(isinstance(Complete(), PredictorModel), "实现 predict 的模型应可实例化")


_TPA_SOURCE = plugin_source(
    "tpa",
    types='{"dataset": "数据集"}',
    class_name="Producer",
    output_schema='{"data": {"type": "dataset"}}',
)

_TPB_SOURCE = plugin_source(
    "tpb",
    class_name="Consumer",
    input_schema='{"data": {"types": ["tpa_1.0@dataset"]}}',
)


def case_cross_plugin_type():
    """A 插件定义类型，B 插件写全名就能接，不需要 import 任何代码。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_zip(
            tmp, "tpa.zip", {"tpa/__init__.py": "", "tpa/components.py": _TPA_SOURCE}
        )
        write_zip(
            tmp, "tpb.zip", {"tpb/__init__.py": "", "tpb/components.py": _TPB_SOURCE}
        )
        registry = Registry().load(tmp)
        check(
            registry.types.get("tpa_1.0@dataset") == "数据集",
            f"A 的类型注册不对：{registry.types}",
        )
        consumer = registry.get_component("tpb", "Consumer")
        check(consumer is not None, "B 组件应加载成功")
        check(
            consumer.input_schema["data"]["types"] == ["tpa_1.0@dataset"],
            f"B 的输入类型应解析到 A 的全名：{consumer.input_schema}",
        )

        raw = {
            "name": "cross",
            "nodes": [
                {
                    "id": "a",
                    "plugin": "tpa",
                    "component": "Producer",
                    "config": {},
                    "inputs": {},
                },
                {
                    "id": "b",
                    "plugin": "tpb",
                    "component": "Consumer",
                    "config": {},
                    "inputs": {"data": {"from": "a", "port": "data"}},
                },
            ],
        }
        report = validate(registry, raw)
        check(report.ok, f"跨插件类型应能接上：{report.errors}")


_ZZ_LIB_COMPONENTS = plugin_source("zz_lib", class_name="Lib")

_AA_DEP_COMPONENTS = plugin_source(
    "aa_dep",
    class_name="Dep",
    extra="from zz_lib.helper import VALUE",
    attrs='    title = f"依赖值 {VALUE}"',
)


def case_load_order_independent():
    """aa_dep 依赖 zz_lib，但 aa_dep.zip 排在前面也必须能加载。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_zip(
            tmp,
            "aa_dep.zip",
            {"aa_dep/__init__.py": "", "aa_dep/components.py": _AA_DEP_COMPONENTS},
        )
        write_zip(
            tmp,
            "zz_lib.zip",
            {
                "zz_lib/__init__.py": "",
                "zz_lib/components.py": _ZZ_LIB_COMPONENTS,
                "zz_lib/helper.py": "VALUE = 42\n",
            },
        )
        registry = Registry().load(tmp)
        dep = registry.get_component("aa_dep", "Dep")
        check(dep is not None, "依赖方应加载成功（不受 zip 文件名顺序影响）")
        check(dep.title == "依赖值 42", f"依赖方的 title 不对：{dep.title!r}")
        check(
            registry.get_component("zz_lib", "Lib") is not None,
            "被依赖的插件也应注册",
        )


def case_short_type():
    registry = Registry().load(ROOT / "plugins")
    check(
        registry.short_type("std_1.0@table") == "std@table",
        f"short_type 结果不对：{registry.short_type('std_1.0@table')!r}",
    )
    check(
        registry.short_type("std_1.0@model") == "std@model",
        f"short_type 结果不对：{registry.short_type('std_1.0@model')!r}",
    )
    check(
        registry.short_type("table") == "table",
        f"不带 @ 的输入应原样返回：{registry.short_type('table')!r}",
    )


def case_reload_same_dir():
    """同一目录 load 两次：内容一致，但组件类被真正重载（不是同一个对象）。"""
    first = Registry().load(ROOT / "plugins")
    second = Registry().load(ROOT / "plugins")
    check(
        sorted(first.plugins) == ["core", "linreg", "std"],
        f"第一次插件：{sorted(first.plugins)}",
    )
    check(
        sorted(second.plugins) == ["core", "linreg", "std"],
        f"第二次插件：{sorted(second.plugins)}",
    )
    check(len(first.components) == 6, f"第一次组件数：{len(first.components)}")
    check(len(second.components) == 6, f"第二次组件数：{len(second.components)}")
    check(first.types == second.types, "两次加载的类型集合应一致")
    first_cls = first.get_component("core", "LoadCSV").cls
    second_cls = second.get_component("core", "LoadCSV").cls
    check(
        first_cls is not second_cls,
        "同一目录重复 load 应真正重载：组件类不能是同一个对象",
    )


def _temp_plugin_source(package, title, component_title, types_literal):
    return plugin_source(
        package,
        title=title,
        types=types_literal,
        attrs=f'    title = "{component_title}"',
    )


def case_reload_other_dir_same_package():
    """两个目录各有一个同名插件：第二个 registry 必须拿到第二个 zip 的内容。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        root = Path(tmp)
        dir_a = root / "a"
        dir_b = root / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        write_zip(
            dir_a,
            "pz1.zip",
            {
                "pz1/__init__.py": "",
                "pz1/components.py": _temp_plugin_source(
                    "pz1", "A 插件", "A 组件", '{"table": "A 的表"}'
                ),
            },
        )
        write_zip(
            dir_b,
            "pz1.zip",
            {
                "pz1/__init__.py": "",
                "pz1/components.py": _temp_plugin_source(
                    "pz1", "B 插件", "B 组件", '{"model": "B 的模型"}'
                ),
            },
        )

        first = Registry().load(dir_a)
        second = Registry().load(dir_b)

        check(
            first.plugins["pz1"].title == "A 插件",
            f"A 的 title 不对：{first.plugins['pz1'].title!r}",
        )
        check(
            second.plugins["pz1"].title == "B 插件",
            f"第二个目录的内容被 A 顶掉了：{second.plugins['pz1'].title!r}",
        )
        check(
            second.plugins["pz1"].types == {"model": "B 的模型"},
            f"B 的 types 不对：{second.plugins['pz1'].types}",
        )
        check(
            second.types.get("pz1_1.0@model") == "B 的模型",
            f"B 的类型注册不对：{second.types}",
        )
        check(
            "pz1_1.0@table" not in second.types,
            f"A 的类型不应串到 B：{second.types}",
        )
        check(
            second.types.get("std_1.0@table") is not None,
            f"std 类型应始终存在：{second.types}",
        )
        check(
            first.types.get("pz1_1.0@table") == "A 的表",
            f"A 的类型注册不对：{first.types}",
        )
        check(
            "pz1_1.0@model" not in first.types,
            f"B 的类型不应串到 A：{first.types}",
        )
        check(
            first.get_component("pz1", "Thing").title == "A 组件",
            "第一次 load 的 registry 不应被第二次 load 污染",
        )
        check(
            second.get_component("pz1", "Thing").title == "B 组件",
            f"B 的组件 title 不对：{second.get_component('pz1', 'Thing').title!r}",
        )


def case_reload_modified_zip():
    """覆盖同一个 zip 文件后重新 load，必须拿到新代码。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_zip(
            tmp,
            "pz2.zip",
            {
                "pz2/__init__.py": "",
                "pz2/components.py": _temp_plugin_source(
                    "pz2", "v1", "旧组件", '{"table": "v1"}'
                ),
            },
        )
        first = Registry().load(tmp)
        check(
            first.get_component("pz2", "Thing").title == "旧组件",
            f"第一次 title 不对：{first.get_component('pz2', 'Thing').title!r}",
        )

        write_zip(
            tmp,
            "pz2.zip",
            {
                "pz2/__init__.py": "",
                "pz2/components.py": _temp_plugin_source(
                    "pz2", "v2", "新组件", '{"table": "v2"}'
                ),
            },
        )
        second = Registry().load(tmp)
        check(
            second.get_component("pz2", "Thing").title == "新组件",
            f"改了 zip 后应拿到新代码，实际 "
            f"{second.get_component('pz2', 'Thing').title!r}",
        )
        check(
            second.plugins["pz2"].title == "v2",
            f"插件 title 没更新：{second.plugins['pz2'].title!r}",
        )


def case_full_type_name_hint():
    """全名写错：文案要说明写的是全名，并给出已注册的同名类型候选。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = plugin_source(
            "ldp25",
            class_name="Bad",
            output_schema='{"out": {"type": "core_1.1@table"}}',
        )
        write_zip(
            tmp, "ldp25.zip", {"ldp25/__init__.py": "", "ldp25/components.py": source}
        )
        expect_raises(
            SchemaError,
            lambda: Registry().load(tmp),
            "未注册",
            "写的是全名",
            "std_1.0@table",
        )


def case_port_level_error_paths():
    """端口类型解析失败时，错误要指到具体端口。"""
    bad_input = plugin_source(
        "ldp26",
        class_name="BadIn",
        input_schema='{"data": {"types": ["nosuch"]}}',
    )
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_zip(
            tmp, "ldp26.zip", {"ldp26/__init__.py": "", "ldp26/components.py": bad_input}
        )
        exc = expect_raises(SchemaError, lambda: Registry().load(tmp), "未注册")
        check(
            ".input.data" in str(exc),
            f"错误信息应指到输入端口 .input.data，实际：{exc}",
        )

    bad_output = plugin_source(
        "ldp27",
        class_name="BadOut",
        output_schema='{"model": {"type": "nosuch"}}',
    )
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_zip(
            tmp, "ldp27.zip", {"ldp27/__init__.py": "", "ldp27/components.py": bad_output}
        )
        exc = expect_raises(SchemaError, lambda: Registry().load(tmp), "未注册")
        check(
            ".output.model" in str(exc),
            f"错误信息应指到输出端口 .output.model，实际：{exc}",
        )


CASES = [
    ("合法临时插件可加载", case_good_plugin_loads),
    ("真实 core.zip / linreg.zip 可加载", case_real_plugins_load),
    ("缺 __init__.py 报错", case_missing_init),
    ("顶层两个目录报错", case_two_top_dirs),
    ("没有子目录报错", case_no_subdirectory),
    ("缺 components.py 报错", case_missing_components_py),
    ("根目录散落 .py 报错", case_root_level_py),
    ("PLUGIN_NAME 缺失报错", case_plugin_name_missing),
    ("PLUGIN_NAME 与目录名不一致报错", case_plugin_name_mismatch),
    ("PLUGIN_VERSION 非法报错", case_plugin_version_invalid),
    ("COMPONENTS 为空报错", case_components_empty),
    ("组件不继承 Component 报错", case_component_not_subclass),
    ("组件重名报错", case_duplicate_component_name),
    ("重复插件名报错", case_duplicate_plugin_name),
    ("依赖缺失报错含包名和 pip 提示", case_missing_requirement),
    ("依赖已安装时正常加载", case_installed_requirement_ok),
    ("PLUGIN_TYPES 类型名非法报错", case_bad_declared_type_name),
    ("输出类型未注册报错", case_unregistered_output_type),
    ("跨插件短名未注册并给出提示", case_short_type_of_other_plugin_hint),
    ("types.py 内部 import 错误报 PluginLoadError", case_types_py_broken_import),
    ("zip 名与插件名不一致报错", case_zip_name_mismatch),
    ("抽象组件加载即报错", case_abstract_component_rejected_at_load),
    ("types.py 语法错报 PluginLoadError", case_types_py_syntax_error),
    ("schema 方法抛异常包装成 PluginLoadError", case_schema_method_raises),
    ("忽略 __MACOSX / ._ 垃圾文件", case_macos_junk_ignored),
    ("全名类型未注册：文案与候选提示", case_full_type_name_hint),
    ("端口类型解析失败指到具体端口", case_port_level_error_paths),
    ("标准类型内置且 std 是伪插件", case_std_builtin),
    ("std 保留命名空间被拒", case_std_namespace_rejected),
    ("PredictorModel 是 ABC", case_predictor_model_contract),
    ("跨插件类型引用不需要 import 代码", case_cross_plugin_type),
    ("加载顺序不影响插件互相 import", case_load_order_independent),
    ("short_type 缩短类型标识", case_short_type),
    ("同一目录重复 load 真正重载", case_reload_same_dir),
    ("不同目录同名插件取第二个 zip 内容", case_reload_other_dir_same_package),
    ("改 zip 内容后重载生效", case_reload_modified_zip),
]


def main():
    return run_cases("loader", CASES)


if __name__ == "__main__":
    sys.exit(main())
