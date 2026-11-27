"""engine.loader 目录插件加载校验测试（契约 docs/CONTRACT.md §2.1）。

临时插件目录全部在系统临时目录现建现删，不动 plugins/。

直接运行：python tests/test_loader.py
"""

import inspect
import io
import os
import sys
import tempfile
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.api import PredictorModel
from engine.errors import PluginLoadError, PluginNameConflict, SchemaError
from engine.loader import add_all_to_sys_path, load_plugin
from engine.registry import Registry
from engine.workflow import validate

from _harness import (
    check,
    component_source,
    expect_raises,
    plugin_source,
    run_cases,
    write_plugin,
    write_zip,
)


def plugin_files(package, name=None, version="1.0"):
    """目录插件的最小文件集；键是插件目录内的相对路径。"""
    return {
        "__init__.py": "",
        "components.py": plugin_source(
            name if name is not None else package, version=version
        ),
    }


def load_only(plugin_dir):
    """契约：``load_plugin`` 要求插件根已挂上 sys.path（Registry.load 负责挂）。

    单插件用例直接调 loader，这里补上「挂根」这一步再按单插件入口加载。
    """
    plugin_dir = Path(plugin_dir)
    add_all_to_sys_path([plugin_dir.parent])
    return load_plugin(plugin_dir, {})


# 坏插件样板：能 import 但缺 PLUGIN_NAME，加载期校验必炸。
_NO_NAME_SOURCE = (
    "from engine.api import Component\n\n"
    'PLUGIN_VERSION = "1.0"\n\n\n'
    "class Thing(Component):\n"
    '    name = "Thing"\n\n\n'
    "COMPONENTS = [Thing]\n"
)


def case_good_plugin_loads():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        plugin_dir = write_plugin(tmp, "ldp0", plugin_files("ldp0"))
        info = load_only(plugin_dir)
        check(info.name == "ldp0", f"插件名不对：{info.name!r}")
        check(info.version == "1.0", f"版本不对：{info.version!r}")
        check(info.title == "测试插件", f"标题不对：{info.title!r}")
        check(info.types == {}, f"types 应为空：{info.types}")
        check(len(info.components) == 1, f"组件数量不对：{info.components}")
        check(
            info.source == str(plugin_dir.resolve()),
            f"source 应是插件目录绝对路径：{info.source!r}",
        )


def case_real_plugins_load():
    core = load_only(ROOT / "plugins" / "core")
    check(core.name == "core", f"core 插件名不对：{core.name!r}")
    check(core.version == "1.0", f"core 版本不对：{core.version!r}")
    check(len(core.components) == 1, f"core 应有 1 个组件：{core.components}")

    fileio = load_only(ROOT / "plugins" / "fileio")
    check(fileio.name == "fileio", f"fileio 插件名不对：{fileio.name!r}")
    check(len(fileio.components) == 5, f"fileio 应有 5 个组件：{fileio.components}")

    table = load_only(ROOT / "plugins" / "table")
    check(table.name == "table", f"table 插件名不对：{table.name!r}")
    check(len(table.components) == 11, f"table 应有 11 个组件：{table.components}")

    split = load_only(ROOT / "plugins" / "split")
    check(split.name == "split", f"split 插件名不对：{split.name!r}")
    check(len(split.components) == 2, f"split 应有 2 个组件：{split.components}")

    ml = load_only(ROOT / "plugins" / "ml")
    check(ml.name == "ml", f"ml 插件名不对：{ml.name!r}")
    check(len(ml.components) == 8, f"ml 应有 8 个组件：{ml.components}")

    registry = Registry().load(ROOT / "plugins")
    check(
        "std_1.0@table" in registry.types,
        f"标准类型应内置：{sorted(registry.types)}",
    )
    check("std_1.0@model" in registry.types, "std_1.0@model 应内置")
    check(
        sorted(registry.plugins) == ["core", "fileio", "ml", "split", "std", "table"],
        f"插件集合应含内置 std：{sorted(registry.plugins)}",
    )
    check(len(registry.components) == 27, f"组件总数应为 27：{len(registry.components)}")


def case_impl_subpackage_import():
    """实现放 impl/ 子包，components.py 按真实插件的写法导入。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = plugin_source(
            "pkgimpl",
            extra="from pkgimpl.impl.thing import TITLE",
            attrs="    title = TITLE",
        )
        write_plugin(
            tmp,
            "pkgimpl",
            {
                "__init__.py": "",
                "impl/__init__.py": "",
                "impl/thing.py": 'TITLE = "来自 impl 子包"\n',
                "components.py": source,
            },
        )
        registry = Registry().load(tmp)
        thing = registry.get_component("pkgimpl", "Thing")
        check(thing is not None, "impl 子包插件应加载成功")
        check(thing.title == "来自 impl 子包", f"title 不对：{thing.title!r}")


def case_missing_init():
    """含 .py 的插件目录缺 __init__.py：加载期报错，不能半个包静默失败。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_plugin(tmp, "ldp1", {"components.py": plugin_source("ldp1")})
        expect_raises(PluginLoadError, lambda: Registry().load(tmp), "__init__.py")


def case_no_components_py_skipped():
    """没有 components.py 的子目录不是插件：进 skipped，不报错。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        plugin_dir = write_plugin(tmp, "ldp4", {"__init__.py": ""})
        registry = Registry().load(tmp, strict=False)
        check("ldp4" not in registry.plugins, "无 components.py 的目录不是插件")
        check(len(registry.skipped) == 1, f"应恰好跳过一条：{registry.skipped}")
        entry = registry.skipped[0]
        check(entry["file"] == "ldp4", f"file 不对：{entry['file']!r}")
        check(entry["path"] == str(plugin_dir.resolve()), f"path 不对：{entry!r}")
        check(
            isinstance(entry["reason"], str) and entry["reason"],
            f"reason 必须非空：{entry['reason']!r}",
        )
        check(
            "没有 components.py" in entry["reason"],
            f"reason 应说明没有 components.py：{entry['reason']!r}",
        )


def case_non_plugin_dir_skipped():
    """插件根下的非插件目录（纯数据）进 skipped，合法插件照常加载。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_plugin(tmp, "ldp44", plugin_files("ldp44"))
        data_dir = Path(tmp) / "data"
        data_dir.mkdir()
        (data_dir / "readme.txt").write_text("不是插件", encoding="utf-8")
        registry = Registry().load(tmp, strict=False)
        check(registry.get_component("ldp44", "Thing") is not None, "合法插件应加载")
        check(len(registry.skipped) == 1, f"应恰好跳过一条：{registry.skipped}")
        check(registry.skipped[0]["file"] == "data", f"file 不对：{registry.skipped}")


def case_zip_in_root_ignored():
    """插件根下的文件（含存量 zip）不参与扫描：既不加载，也不进 skipped。

    契约 §2.1：插件 = 插件根下的子目录；zip 只作传输用途。
    """
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_plugin(tmp, "ldp40", plugin_files("ldp40"))
        write_zip(
            tmp,
            "ldp40_old.zip",
            {
                "ldp40_old/__init__.py": "",
                "ldp40_old/components.py": plugin_source("ldp40_old"),
            },
        )
        registry = Registry().load(tmp, strict=False)
        check(registry.get_component("ldp40", "Thing") is not None, "目录插件应加载")
        check(
            "ldp40_old" not in registry.plugins,
            f"根下 zip 不应被加载：{sorted(registry.plugins)}",
        )
        check(
            registry.skipped == [],
            f"根下文件不参与扫描，不应产生 skipped：{registry.skipped}",
        )


def case_plugin_name_missing():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        plugin_dir = write_plugin(
            tmp, "ldp6", {"__init__.py": "", "components.py": _NO_NAME_SOURCE}
        )
        expect_raises(
            PluginLoadError, lambda: load_only(plugin_dir), "PLUGIN_NAME 缺失或不合法"
        )


def case_plugin_name_mismatch():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        plugin_dir = write_plugin(tmp, "ldp7", plugin_files("ldp7", name="other"))
        expect_raises(
            PluginLoadError,
            lambda: load_only(plugin_dir),
            "目录名",
        )


def case_plugin_version_invalid():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        plugin_dir = write_plugin(tmp, "ldp8", plugin_files("ldp8", version="1"))
        expect_raises(
            PluginLoadError, lambda: load_only(plugin_dir), "PLUGIN_VERSION 缺失或不合法"
        )


def case_components_empty():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = plugin_source("ldp9", components="COMPONENTS = []")
        plugin_dir = write_plugin(tmp, "ldp9", {"__init__.py": "", "components.py": source})
        expect_raises(
            PluginLoadError, lambda: load_only(plugin_dir), "COMPONENTS 必须是非空列表"
        )


def case_component_not_subclass():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = plugin_source(
            "ldp10",
            component='class NotComponent:\n    name = "Nope"',
            components="COMPONENTS = [NotComponent]",
        )
        write_plugin(tmp, "ldp10", {"__init__.py": "", "components.py": source})
        expect_raises(
            PluginLoadError,
            lambda: Registry().load(tmp),
            "不是 engine.api.Component 的子类",
        )


def case_duplicate_component_name():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = plugin_source(
            "ldp11",
            component=component_source("A", component_name="Same")
            + '\n\n\nclass B(A):\n    name = "Same"',
            components="COMPONENTS = [A, B]",
        )
        write_plugin(tmp, "ldp11", {"__init__.py": "", "components.py": source})
        expect_raises(PluginLoadError, lambda: Registry().load(tmp), "组件名重复")


def case_duplicate_plugin_name():
    """同名插件目录放在两个根里，先加载一个再加载另一个，第二次必须报重复。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        root = Path(tmp)
        first_dir = root / "a"
        second_dir = root / "b"
        first_dir.mkdir()
        second_dir.mkdir()
        write_plugin(first_dir, "ldp12", plugin_files("ldp12"))
        write_plugin(second_dir, "ldp12", plugin_files("ldp12"))
        registry = Registry()
        registry.load(first_dir)
        expect_raises(
            PluginLoadError, lambda: registry.load(second_dir), "插件名重复"
        )


def case_multiple_plugins_dirs():
    """两个根各一个插件，一次 load 都进来。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        root = Path(tmp)
        dir_a = root / "a"
        dir_b = root / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        write_plugin(dir_a, "ldp30", plugin_files("ldp30"))
        write_plugin(dir_b, "ldp31", plugin_files("ldp31"))
        registry = Registry().load(dir_a, dir_b)
        check(
            registry.get_component("ldp30", "Thing") is not None,
            "第一个目录的插件没加载",
        )
        check(
            registry.get_component("ldp31", "Thing") is not None,
            "第二个目录的插件没加载",
        )
        check(
            sorted(registry.plugins) == ["ldp30", "ldp31", "std"],
            f"插件集合不对：{sorted(registry.plugins)}",
        )


def case_same_dir_twice():
    """同一根传两次：按绝对路径去重，插件只加载一次，不报重复。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_plugin(tmp, "ldp32", plugin_files("ldp32"))
        registry = Registry().load(tmp, tmp)
        check(registry.get_component("ldp32", "Thing") is not None, "插件应加载")
        check(
            sorted(registry.plugins) == ["ldp32", "std"],
            f"插件应只出现一次：{sorted(registry.plugins)}",
        )


def case_duplicate_plugin_across_dirs():
    """不同根里的同名插件一次 load 仍要报重复。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        root = Path(tmp)
        dir_a = root / "a"
        dir_b = root / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        write_plugin(dir_a, "ldp33", plugin_files("ldp33"))
        write_plugin(dir_b, "ldp33", plugin_files("ldp33"))
        expect_raises(
            PluginLoadError, lambda: Registry().load(dir_a, dir_b), "插件名重复"
        )


def case_duplicate_plugin_name_after_broken_root():
    """先给的根里那份坏了（宽容模式会被跳过），跨根同名的预检查仍要在挂载前报重复。

    契约 §2.1：预检查在任何插件根挂载之前做。否则坏的那份被跳过、好的那份
    静默顶上（或反过来登记自己的 source 却跑先挂根里的代码），两种模式都不报错。
    """
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        root = Path(tmp)
        dir_a = root / "a"
        dir_b = root / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        broken = plugin_files("ldp47")
        broken["requirements.txt"] = "definitely_missing_pkg_ldp47\n"
        first = write_plugin(dir_a, "ldp47", broken)
        second = write_plugin(dir_b, "ldp47", plugin_files("ldp47"))
        for strict in (False, True):
            exc = expect_raises(
                PluginNameConflict,
                lambda strict=strict: Registry().load(dir_a, dir_b, strict=strict),
                "插件名重复",
            )
            text = str(exc)
            check(
                str(first.resolve()) in text,
                f"strict={strict} 文案应含第一个插件目录的绝对路径：{text!r}",
            )
            check(
                str(second.resolve()) in text,
                f"strict={strict} 文案应含第二个插件目录的绝对路径：{text!r}",
            )


def case_duplicate_plugin_name_after_broken_structure():
    """第一份结构校验失败（缺 __init__.py），第二份合法同名：挂载前仍要报重复。

    预检查若只看结构通过的 valid，A 会被跳过，B 会「加载成功」——但 A 的
    同名目录在 sys.path 上是命名空间包，B 的 components 实际 import 到 A 的
    代码，source 却登记 B 的目录。这条锁「不许跑别人代码、登记自己来源」。
    """
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        root = Path(tmp)
        dir_a = root / "a"
        dir_b = root / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        first = write_plugin(
            dir_a, "ldp48", {"components.py": plugin_source("ldp48")}
        )
        second = write_plugin(dir_b, "ldp48", plugin_files("ldp48"))
        for strict in (False, True):
            exc = expect_raises(
                PluginNameConflict,
                lambda strict=strict: Registry().load(dir_a, dir_b, strict=strict),
                "插件名重复",
            )
            text = str(exc)
            check(
                str(first.resolve()) in text,
                f"strict={strict} 文案应含第一个插件目录的绝对路径：{text!r}",
            )
            check(
                str(second.resolve()) in text,
                f"strict={strict} 文案应含第二个插件目录的绝对路径：{text!r}",
            )


def case_missing_requirement():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        entries = plugin_files("ldp13")
        entries["requirements.txt"] = "definitely_missing_pkg_xyz>=1.0\n"
        plugin_dir = write_plugin(tmp, "ldp13", entries)
        exc = expect_raises(
            PluginLoadError, lambda: load_only(plugin_dir), "pip install"
        )
        check(
            "definitely_missing_pkg_xyz" in str(exc),
            f"错误信息里应包含缺失的包名，实际：{exc}",
        )


def case_installed_requirement_ok():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        entries = plugin_files("ldp14")
        entries["requirements.txt"] = "pandas\n"
        plugin_dir = write_plugin(tmp, "ldp14", entries)
        info = load_only(plugin_dir)
        check(info.name == "ldp14", "已安装依赖时不应该报错")


def case_version_constraint_warning():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        entries = plugin_files("ldp34")
        entries["requirements.txt"] = "pandas>=2.0\n"
        plugin_dir = write_plugin(tmp, "ldp34", entries)
        err = io.StringIO()
        with redirect_stderr(err):
            info = load_only(plugin_dir)
        text = err.getvalue()
    check(info.name == "ldp34", "带版本约束但依赖已安装时应能加载")
    check("只检查是否已安装" in text, f"stderr 缺少版本说明：{text!r}")
    check("不校验版本" in text, f"stderr 缺少版本说明：{text!r}")


def case_importable_package_name_rejected():
    """标准库和已安装第三方包的名字都会被 import 顶掉，加载期就拒绝。"""
    for name in ("uuid", "pandas"):
        with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
            write_plugin(tmp, name, plugin_files(name))
            exc = expect_raises(
                PluginLoadError, lambda: Registry().load(tmp), name, "同名"
            )
            text = str(exc)
            check("已安装" in text, f"{name} 的错误信息应说明与已安装模块同名：{text!r}")
            check("标准库" in text, f"{name} 的错误信息应提到标准库：{text!r}")


def case_plugin_own_package_not_conflict():
    """插件根挂上 sys.path 后，不能再把自己的包名当成「已安装模块」拒绝。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        plugin_dir = write_plugin(tmp, "ldp37", plugin_files("ldp37"))
        load_only(plugin_dir)  # 先把插件根挂上 sys.path（Registry.load 的同一套挂载）
        registry = Registry().load(tmp)
    check("ldp37" in registry.plugins, f"自身包名不应冲突：{sorted(registry.plugins)}")


def case_name_check_before_mount():
    """名字校验必须先于「插件根挂 sys.path」：
    被 PathFinder 查到的名字要拒绝，且失败后插件根不能残留、同根其它插件不能被加载一半。"""
    import uuid

    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        root = str(Path(tmp).resolve())
        # 合法兄弟插件排在前（目录名排序），用来证明失败时一个都不会被导入
        write_plugin(tmp, "aaa_ok", plugin_files("aaa_ok"))
        write_plugin(tmp, "uuid", plugin_files("uuid"))
        registry = Registry()
        expect_raises(PluginLoadError, lambda: registry.load(tmp), "uuid", "同名")
        check(root not in sys.path, f"校验失败时插件根不能留在 sys.path：{sys.path[:3]}")
        check(
            "aaa_ok" not in registry.plugins and "uuid" not in registry.plugins,
            f"失败时不能加载半个包：{sorted(registry.plugins)}",
        )
        check(sys.modules.get("uuid") is uuid, "标准库 uuid 不能被插件顶掉或重建")


def case_stdlib_module_rejected_without_breaking_process():
    """sys 插件被拒之外，还要保证进程里的真 sys 没被 purge 成残骸。"""
    import importlib.util

    real_sys = sys.modules.get("sys")
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_plugin(tmp, "sys", plugin_files("sys"))
        expect_raises(
            PluginLoadError, lambda: Registry().load(tmp), "sys", "同名"
        )

    check(
        sys.modules.get("sys") is real_sys,
        "真 sys 模块被删除或替换了（插件加载先 purge 再检查的老 bug 回归）",
    )
    check(
        hasattr(sys.modules.get("sys"), "path"),
        "sys 模块变成了缺 path 的残骸",
    )
    try:
        # 任意不存在的模块名即可：这里只验证 sys 的查找链没被 purge 坏。
        importlib.util.find_spec("engine_sys_probe_absent_module")
    except AttributeError as exc:
        raise AssertionError(
            f"find_spec 抛 AttributeError，说明 sys 已残：{exc}"
        ) from None


def case_plugin_title_not_string():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = plugin_source("ldp35").replace(
            'PLUGIN_TITLE = "测试插件"', "PLUGIN_TITLE = 123"
        )
        plugin_dir = write_plugin(
            tmp, "ldp35", {"__init__.py": "", "components.py": source}
        )
        expect_raises(PluginLoadError, lambda: load_only(plugin_dir), "PLUGIN_TITLE")


def case_component_title_not_string():
    """组件级 title 不是字符串要在加载期拒绝，不能留到 Studio 拼节点时才炸。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = plugin_source("ldp36", attrs="    title = 123")
        write_plugin(tmp, "ldp36", {"__init__.py": "", "components.py": source})
        exc = expect_raises(
            PluginLoadError, lambda: Registry().load(tmp), "title 必须是字符串"
        )
        check(
            "ldp36.Thing" in str(exc),
            f"错误信息应指到出问题的组件，实际：{exc}",
        )


def case_component_desc_not_string():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = plugin_source("ldp47", attrs="    desc = 123")
        write_plugin(tmp, "ldp47", {"__init__.py": "", "components.py": source})
        exc = expect_raises(
            PluginLoadError, lambda: Registry().load(tmp), "desc 必须是字符串"
        )
        check(
            "ldp47.Thing" in str(exc),
            f"错误信息应指到出问题的组件，实际：{exc}",
        )


def case_unregistered_output_type():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = plugin_source("ldp16", output_schema='{"out": {"type": "nosuch"}}')
        write_plugin(tmp, "ldp16", {"__init__.py": "", "components.py": source})
        expect_raises(SchemaError, lambda: Registry().load(tmp), "未注册")


def case_short_type_of_other_plugin_hint():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        provider = plugin_source("ldp17a")
        consumer = plugin_source(
            "ldp17b", class_name="Consumer", input_schema='{"data": {"types": ["table"]}}'
        )
        write_plugin(
            tmp,
            "ldp17a",
            {
                "__init__.py": "",
                "components.py": provider,
                "types.py": 'TYPES = {"table": "表"}\n',
            },
        )
        write_plugin(tmp, "ldp17b", {"__init__.py": "", "components.py": consumer})
        expect_raises(
            SchemaError, lambda: Registry().load(tmp), "未注册", "ldp17a_1.0@table"
        )


def case_types_py_broken_import():
    """types.py 自己的 import 写错必须报 PluginLoadError，不能当成没有 types.py。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        entries = plugin_files("ldp18")
        entries["types.py"] = "import definitely_missing_module_xyz\n\nTYPES = {}\n"
        plugin_dir = write_plugin(tmp, "ldp18", entries)
        expect_raises(
            PluginLoadError,
            lambda: load_only(plugin_dir),
            "types.py",
            "definitely_missing_module_xyz",
        )


def case_abstract_component_rejected_at_load():
    """缺 invoke 的组件类在加载时就该被拒，registry 里不会出现它。"""
    source = plugin_source("ldp20", class_name="NoInvoke", with_invoke=False)
    registry = Registry()
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_plugin(tmp, "ldp20", {"__init__.py": "", "components.py": source})
        exc = expect_raises(
            PluginLoadError, lambda: registry.load(tmp), "未实现的抽象方法"
        )
        check("invoke" in str(exc), f"错误信息应指出缺 invoke：{exc}")
    check(registry.components == {}, f"抽象组件不应被注册：{registry.components}")


def case_types_py_syntax_error():
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        entries = plugin_files("ldp21")
        entries["types.py"] = "def broken(\n"
        plugin_dir = write_plugin(tmp, "ldp21", entries)
        expect_raises(PluginLoadError, lambda: load_only(plugin_dir), "types.py")


def case_schema_method_raises():
    """组件 schema 方法抛非 WorkflowError 时，包装成 PluginLoadError。"""
    source = plugin_source(
        "ldp22",
        class_name="BoomSchema",
        config_body='raise RuntimeError("schema 读炸了")',
    )
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_plugin(tmp, "ldp22", {"__init__.py": "", "components.py": source})
        expect_raises(
            PluginLoadError,
            lambda: Registry().load(tmp),
            "读取 schema 失败",
            "schema 读炸了",
        )


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
    """std 是保留命名空间，插件目录不能叫 std（名字校验在 Registry.load 里）。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_plugin(
            tmp, "std", {"__init__.py": "", "components.py": plugin_source("std")}
        )
        expect_raises(
            PluginLoadError,
            lambda: Registry().load(tmp),
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
        write_plugin(
            tmp,
            "tpa",
            {
                "__init__.py": "",
                "components.py": _TPA_SOURCE,
                "types.py": 'TYPES = {"dataset": "数据集"}\n',
            },
        )
        write_plugin(tmp, "tpb", {"__init__.py": "", "components.py": _TPB_SOURCE})
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
    """aa_dep 依赖 zz_lib，但 aa_dep 目录排在前面也必须能加载。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_plugin(
            tmp, "aa_dep", {"__init__.py": "", "components.py": _AA_DEP_COMPONENTS}
        )
        write_plugin(
            tmp,
            "zz_lib",
            {
                "__init__.py": "",
                "components.py": _ZZ_LIB_COMPONENTS,
                "helper.py": "VALUE = 42\n",
            },
        )
        registry = Registry().load(tmp)
        dep = registry.get_component("aa_dep", "Dep")
        check(dep is not None, "依赖方应加载成功（不受目录顺序影响）")
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
    """同一根 load 两次：内容一致，但组件类被真正重载（不是同一个对象）。"""
    first = Registry().load(ROOT / "plugins")
    second = Registry().load(ROOT / "plugins")
    check(
        sorted(first.plugins) == ["core", "fileio", "ml", "split", "std", "table"],
        f"第一次插件：{sorted(first.plugins)}",
    )
    check(
        sorted(second.plugins) == ["core", "fileio", "ml", "split", "std", "table"],
        f"第二次插件：{sorted(second.plugins)}",
    )
    check(len(first.components) == 27, f"第一次组件数：{len(first.components)}")
    check(len(second.components) == 27, f"第二次组件数：{len(second.components)}")
    check(first.types == second.types, "两次加载的类型集合应一致")
    first_cls = first.get_component("fileio", "LoadCSV").cls
    second_cls = second.get_component("fileio", "LoadCSV").cls
    check(
        first_cls is not second_cls,
        "同一目录重复 load 应真正重载：组件类不能是同一个对象",
    )


def _temp_plugin_files(package, title, component_title, types_literal):
    return {
        "__init__.py": "",
        "components.py": plugin_source(
            package, title=title, attrs=f'    title = "{component_title}"'
        ),
        "types.py": f"TYPES = {types_literal}\n",
    }


def case_reload_other_dir_same_package():
    """两个根各有一个同名插件：第二个 registry 必须拿到第二个目录的内容。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        root = Path(tmp)
        dir_a = root / "a"
        dir_b = root / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        write_plugin(
            dir_a,
            "pz1",
            _temp_plugin_files("pz1", "A 插件", "A 组件", '{"table": "A 的表"}'),
        )
        write_plugin(
            dir_b,
            "pz1",
            _temp_plugin_files("pz1", "B 插件", "B 组件", '{"model": "B 的模型"}'),
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


def case_reload_modified_dir():
    """改目录内容后重新 load：连新增的模块也必须被看见（FileFinder 缓存要失效）。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        impl_dir = Path(tmp) / "pz2" / "impl"
        write_plugin(
            tmp,
            "pz2",
            {
                "__init__.py": "",
                "components.py": plugin_source(
                    "pz2",
                    extra="from pz2.impl.one import TITLE",
                    attrs="    title = TITLE",
                ),
                "impl/__init__.py": "",
                "impl/one.py": 'TITLE = "旧组件"\n',
            },
        )
        first = Registry().load(tmp)
        check(
            first.get_component("pz2", "Thing").title == "旧组件",
            f"第一次 title 不对：{first.get_component('pz2', 'Thing').title!r}",
        )
        frozen_mtime = impl_dir.stat().st_mtime_ns

        # 第二版：components.py 改为导入新增的 impl/two.py（one.py 保持不动）。
        # 只靠 sys.modules 清理不够：文件清单还在 FileFinder 的目录缓存里，
        # 不调 importlib.invalidate_caches() 会看不到新文件。
        # 源码长度要变化：Python 的 pyc 缓存按「大小 + 秒级 mtime」判断，
        # 同长度同秒的改写会复用旧字节码，掩盖掉真正要测的 FileFinder 缓存。
        write_plugin(
            tmp,
            "pz2",
            {
                "components.py": plugin_source(
                    "pz2",
                    extra=(
                        "from pz2.impl.two import TITLE\n"
                        "# v2: 新增 impl/two.py，长度与 v1 不同"
                    ),
                    attrs="    title = TITLE",
                ),
                "impl/two.py": 'TITLE = "新组件"\n',
            },
        )
        # 目录清单缓存按目录 mtime 判新旧：把 impl/ 的 mtime 复位，
        # 模拟「缓存看起来仍然新鲜、但文件清单已经变了」——没有
        # invalidate_caches() 就会看不见新增的 impl/two.py。
        os.utime(impl_dir, ns=(impl_dir.stat().st_atime_ns, frozen_mtime))
        second = Registry().load(tmp)
        check(
            second.get_component("pz2", "Thing").title == "新组件",
            f"改了目录内容后应拿到新代码，实际 "
            f"{second.get_component('pz2', 'Thing').title!r}",
        )
        check(
            second.plugins["pz2"].version == "1.0",
            f"版本不应被上一次加载污染：{second.plugins['pz2'].version!r}",
        )


def case_full_type_name_hint():
    """全名写错：文案要说明写的是全名，并给出已注册的同名类型候选。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        source = plugin_source(
            "ldp25",
            class_name="Bad",
            output_schema='{"out": {"type": "core_1.1@table"}}',
        )
        write_plugin(tmp, "ldp25", {"__init__.py": "", "components.py": source})
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
        write_plugin(tmp, "ldp26", {"__init__.py": "", "components.py": bad_input})
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
        write_plugin(tmp, "ldp27", {"__init__.py": "", "components.py": bad_output})
        exc = expect_raises(SchemaError, lambda: Registry().load(tmp), "未注册")
        check(
            ".output.model" in str(exc),
            f"错误信息应指到输出端口 .output.model，实际：{exc}",
        )


def case_tolerant_failed_plugin_purged():
    """宽容模式：加载失败的插件要清掉 sys.modules 残留，不能留半个包。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_plugin(
            tmp, "shadowmod", {"__init__.py": "", "components.py": _NO_NAME_SOURCE}
        )
        registry = Registry().load(tmp, strict=False)
        check(len(registry.skipped) == 1, f"应恰好跳过一条：{registry.skipped}")
        check(
            "PLUGIN_NAME" in registry.skipped[0]["reason"],
            f"reason 应是缺 PLUGIN_NAME：{registry.skipped[0]}",
        )
        check("shadowmod" not in sys.modules, "坏包的 sys.modules 残留必须清掉")


def case_tolerant_plugin_name_conflict_is_hard_error():
    """宽容模式也不吞同名插件：PluginNameConflict 文案带两个目录的绝对路径。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        root = Path(tmp)
        dir_a = root / "a"
        dir_b = root / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        first = write_plugin(dir_a, "ldp41", plugin_files("ldp41"))
        second = write_plugin(dir_b, "ldp41", plugin_files("ldp41"))
        exc = expect_raises(
            PluginNameConflict,
            lambda: Registry().load(dir_a, dir_b, strict=False),
            "插件名重复",
        )
        text = str(exc)
        check(str(first.resolve()) in text, f"文案应含第一个插件目录的绝对路径：{text!r}")
        check(str(second.resolve()) in text, f"文案应含第二个插件目录的绝对路径：{text!r}")


def case_strict_hard_errors_without_skips():
    """strict=True：坏插件目录直接抛，skipped 为空；同名冲突仍是 PluginNameConflict。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_plugin(tmp, "ldp45", {"__init__.py": "", "components.py": _NO_NAME_SOURCE})
        registry = Registry()
        expect_raises(
            PluginLoadError,
            lambda: registry.load(tmp, strict=True),
            "PLUGIN_NAME",
        )
        check(registry.skipped == [], f"strict 模式不应有 skipped：{registry.skipped}")

    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        root = Path(tmp)
        dir_a = root / "a"
        dir_b = root / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        write_plugin(dir_a, "ldp43", plugin_files("ldp43"))
        write_plugin(dir_b, "ldp43", plugin_files("ldp43"))
        exc = expect_raises(
            PluginNameConflict,
            lambda: Registry().load(dir_a, dir_b, strict=True),
            "插件名重复",
        )
        check(
            isinstance(exc, PluginLoadError),
            f"PluginNameConflict 应是 PluginLoadError 子类：{type(exc)}",
        )


def case_tolerant_keeps_schema_errors():
    """宽容模式不吞 schema 错误：插件加载成功但类型未注册仍抛，且不进 skipped。"""
    source = plugin_source(
        "ldp42",
        class_name="Bad",
        output_schema='{"out": {"type": "nosuch"}}',
    )
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_plugin(tmp, "ldp42", {"__init__.py": "", "components.py": source})
        registry = Registry()
        expect_raises(
            SchemaError,
            lambda: registry.load(tmp, strict=False),
            "未注册",
        )
        check(
            registry.skipped == [],
            f"schema 错误不算跳过，skipped 应为空：{registry.skipped}",
        )


def case_default_load_is_strict():
    """不传 strict 就是严格模式：坏插件目录直接抛，保住 CLI 行为。"""
    with tempfile.TemporaryDirectory(prefix="engine_loader_test_") as tmp:
        write_plugin(
            tmp, "ldp46", {"__init__.py": "", "components.py": _NO_NAME_SOURCE}
        )
        registry = Registry()
        expect_raises(
            PluginLoadError,
            lambda: registry.load(tmp),
            "PLUGIN_NAME",
        )
        check(registry.skipped == [], f"默认严格模式不应有 skipped：{registry.skipped}")


def case_registry_load_signature():
    """Registry.load 的公开签名是契约（Studio 按此调用）：``load(*plugins_dirs, strict=True)``。"""
    params = inspect.signature(Registry.load).parameters
    check(list(params) == ["self", "plugins_dirs", "strict"], f"参数名/顺序不对：{list(params)}")
    check(params["plugins_dirs"].kind is inspect.Parameter.VAR_POSITIONAL, "*plugins_dirs 必须是可变位置参数")
    check(params["strict"].kind is inspect.Parameter.KEYWORD_ONLY, "strict 必须是仅关键字参数")
    check(params["strict"].default is True, f"strict 默认必须是 True：{params['strict'].default!r}")


CASES = [
    ("合法临时插件可加载", case_good_plugin_loads),
    ("真实插件目录可加载", case_real_plugins_load),
    ("impl 子包实现可导入", case_impl_subpackage_import),
    ("缺 __init__.py 报错", case_missing_init),
    ("无 components.py 的目录进 skipped", case_no_components_py_skipped),
    ("非插件目录进 skipped", case_non_plugin_dir_skipped),
    ("插件根下的存量 zip 不参与扫描", case_zip_in_root_ignored),
    ("PLUGIN_NAME 缺失报错", case_plugin_name_missing),
    ("PLUGIN_NAME 与目录名不一致报错", case_plugin_name_mismatch),
    ("PLUGIN_VERSION 非法报错", case_plugin_version_invalid),
    ("COMPONENTS 为空报错", case_components_empty),
    ("组件不继承 Component 报错", case_component_not_subclass),
    ("组件重名报错", case_duplicate_component_name),
    ("重复插件名报错", case_duplicate_plugin_name),
    ("多根：两个根各一个插件都加载", case_multiple_plugins_dirs),
    ("多根：同一根传两次去重", case_same_dir_twice),
    ("多根：不同根同名插件报重复", case_duplicate_plugin_across_dirs),
    ("多根：先给的根里同名那份坏了仍报重复", case_duplicate_plugin_name_after_broken_root),
    ("多根：先给的根里结构校验失败的同名仍报重复", case_duplicate_plugin_name_after_broken_structure),
    ("依赖缺失报错含包名和 pip 提示", case_missing_requirement),
    ("依赖已安装时正常加载", case_installed_requirement_ok),
    ("requirements 带版本约束时加载成功并警告", case_version_constraint_warning),
    ("插件名与可导入模块（标准库/第三方包）同名被拒", case_importable_package_name_rejected),
    ("插件自身包名不算冲突", case_plugin_own_package_not_conflict),
    ("名字校验先于挂载且不留半个包", case_name_check_before_mount),
    ("内置模块 sys 被拒且进程不被破坏", case_stdlib_module_rejected_without_breaking_process),
    ("插件 title 必须是字符串", case_plugin_title_not_string),
    ("组件 title 必须是字符串", case_component_title_not_string),
    ("组件 desc 必须是字符串", case_component_desc_not_string),
    ("输出类型未注册报错", case_unregistered_output_type),
    ("跨插件短名未注册并给出提示", case_short_type_of_other_plugin_hint),
    ("types.py 内部 import 错误报 PluginLoadError", case_types_py_broken_import),
    ("抽象组件加载即报错", case_abstract_component_rejected_at_load),
    ("types.py 语法错报 PluginLoadError", case_types_py_syntax_error),
    ("schema 方法抛异常包装成 PluginLoadError", case_schema_method_raises),
    ("全名类型未注册：文案与候选提示", case_full_type_name_hint),
    ("端口类型解析失败指到具体端口", case_port_level_error_paths),
    ("标准类型内置且 std 是伪插件", case_std_builtin),
    ("std 保留命名空间被拒", case_std_namespace_rejected),
    ("PredictorModel 是 ABC", case_predictor_model_contract),
    ("跨插件类型引用不需要 import 代码", case_cross_plugin_type),
    ("加载顺序不影响插件互相 import", case_load_order_independent),
    ("short_type 缩短类型标识", case_short_type),
    ("同一根重复 load 真正重载", case_reload_same_dir),
    ("不同根同名插件取第二个目录内容", case_reload_other_dir_same_package),
    ("改目录内容后重载生效", case_reload_modified_dir),
    ("宽容模式：失败插件清掉 sys.modules 残留", case_tolerant_failed_plugin_purged),
    ("宽容模式：同名插件仍是硬错误", case_tolerant_plugin_name_conflict_is_hard_error),
    ("严格模式：硬错误且 skipped 为空", case_strict_hard_errors_without_skips),
    ("宽容模式：schema 错误不吞且不进 skipped", case_tolerant_keeps_schema_errors),
    ("默认参数是严格模式", case_default_load_is_strict),
    ("Registry.load 签名与 strict 语义", case_registry_load_signature),
]


def main():
    return run_cases("loader", CASES)


if __name__ == "__main__":
    sys.exit(main())
