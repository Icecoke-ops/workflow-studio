"""插件 zip 的发现、校验与加载。

插件 zip 结构（``__init__.py`` 是硬要求，zipimport 不支持隐式命名空间包）：

    school_bean.zip
    └─ school_bean/
       ├─ __init__.py
       ├─ components.py      # 只做声明：PLUGIN_* 常量 + COMPONENTS 清单
       ├─ types.py           # 可选：TYPES = {"短类型名": "说明"}
       ├─ requirements.txt   # 可选：依赖清单，启动时检查是否已安装
       └─ ...                # 任意子目录 / 源文件 / 数据文件
"""

import importlib
import importlib.metadata
import importlib.util
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import stdtypes
from .errors import PluginLoadError
from .typeid import is_name, is_version

_REQ_SPLIT = re.compile(r"[<>=!~\[; ]")

# importlib.metadata 每次查询都会扫一遍 sys.path（包括所有插件 zip），
# 按发行名缓存一下，N 个插件 × M 个依赖不要重复扫。
#
# ponytail: 扫描过程会留下未关闭的 ZipFile 句柄，Windows 上表现为插件 zip 删不掉。
#           现在插件一次加载到底、进程退出即释放，影响仅限「同进程反复 build+reload 后删旧 zip」。
#           真要做插件热卸载，再引入显式的句柄回收。
_INSTALLED = {}


def _installed_version(dist):
    key = dist.lower()
    if key in _INSTALLED:
        return _INSTALLED[key]
    try:
        _INSTALLED[key] = importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        _INSTALLED[key] = None
    except Exception:
        _INSTALLED[key] = None
    return _INSTALLED[key]


@dataclass
class PluginInfo:
    name: str
    version: str
    title: str
    types: dict = field(default_factory=dict)
    components: list = field(default_factory=list)
    source: str = ""


def find_zips(plugins_dir):
    path = Path(plugins_dir)
    if not path.is_dir():
        raise PluginLoadError(f"插件目录不存在：{path.resolve()}")
    return sorted(path.glob("*.zip"))


def add_all_to_sys_path(zip_paths):
    """先把所有插件 zip 挂上 sys.path，再逐个 import。

    这样插件之间互相 import 就不受文件名顺序影响（B 依赖 A 时，
    A 是否排在前面不该决定成败）。
    """
    for zip_path in zip_paths:
        zip_str = str(Path(zip_path).resolve())
        if zip_str not in sys.path:
            sys.path.insert(0, zip_str)


def _is_junk(name):
    """忽略 macOS 打包垃圾（__MACOSX/ 与 ._* 影子文件）。"""
    parts = name.split("/")
    return "__MACOSX" in parts or parts[-1].startswith("._")


def _package_name(zip_path):
    """zip 顶层必须恰好一个插件目录，且每个含 .py 的目录都要有 __init__.py。"""
    with zipfile.ZipFile(zip_path) as zf:
        names = [n.replace("\\", "/") for n in zf.namelist()]
    names = [n for n in names if not _is_junk(n)]

    tops = sorted({n.split("/")[0] for n in names if "/" in n})
    if len(tops) != 1:
        raise PluginLoadError(
            f"{zip_path.name}: zip 顶层必须恰好一个插件目录，实际 {tops or '没有子目录'}"
        )
    package = tops[0]
    if package == stdtypes.PLUGIN_NAME:
        raise PluginLoadError(
            f"{zip_path.name}: {package!r} 是引擎保留的命名空间，插件请换个名字"
        )
    stem = Path(zip_path).stem
    if stem != package:
        raise PluginLoadError(
            f"{zip_path.name}: zip 文件名主干必须是插件名 {package!r}，实际 {stem!r}"
        )
    files = set(names)

    root_py = [n for n in names if "/" not in n and n.endswith(".py")]
    if root_py:
        raise PluginLoadError(f"{zip_path.name}: 源文件必须放在 {package}/ 目录下，发现根目录文件 {root_py}")

    dirs = {n.rsplit("/", 1)[0] for n in names if n.endswith(".py") and "/" in n}
    for directory in sorted(dirs):
        if f"{directory}/__init__.py" not in files:
            raise PluginLoadError(
                f"{zip_path.name}: 目录 {directory}/ 缺少 __init__.py（zipimport 要求）"
            )
    if f"{package}/components.py" not in files:
        raise PluginLoadError(f"{zip_path.name}: 缺少 {package}/components.py")
    return package


def _check_requirements(zip_path, package):
    """requirements.txt 里的依赖没装就报错，不自动安装。"""
    with zipfile.ZipFile(zip_path) as zf:
        try:
            text = zf.read(f"{package}/requirements.txt").decode("utf-8")
        except KeyError:
            return

    missing = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        dist = _REQ_SPLIT.split(line, 1)[0].strip()
        if not dist:
            continue
        if _installed_version(dist) is None:
            missing.append(dist)
    if missing:
        raise PluginLoadError(
            f"{zip_path.name}: 缺少依赖 {', '.join(sorted(set(missing)))}，"
            f"请先安装：pip install {' '.join(sorted(set(missing)))}"
        )


def _purge_modules(package):
    """同进程重复加载同名插件前，先清掉旧模块。

    否则 sys.modules 会直接复用旧代码：改了 zip 再 load 拿到的还是旧类，
    甚至第二个目录的同名插件会被第一个目录的内容静默顶掉。
    """
    stale = [n for n in sys.modules if n == package or n.startswith(package + ".")]
    for name in stale:
        del sys.modules[name]


def _import_components(zip_path, package):
    zip_str = str(Path(zip_path).resolve())
    if zip_str not in sys.path:
        sys.path.insert(0, zip_str)
    _purge_modules(package)
    importlib.invalidate_caches()
    try:
        return importlib.import_module(f"{package}.components")
    except Exception as exc:  # 插件自己的导入错误要原样带出来
        raise PluginLoadError(f"{zip_path.name}: 导入 {package}.components 失败：{exc}") from exc


def _collect_types(module, package):
    types = {}
    declared = getattr(module, "PLUGIN_TYPES", None)
    if declared is not None:
        if not isinstance(declared, dict):
            raise PluginLoadError(f"{package}: PLUGIN_TYPES 必须是 dict")
        types.update(declared)
    # 区分「没有 types.py」和「types.py 里自己的 import 写错了」：
    # 后者必须报出来，不能当成没有 types.py 静默跳过。
    try:
        spec = importlib.util.find_spec(f"{package}.types")
    except (ImportError, ValueError):
        spec = None
    except Exception as exc:  # find_spec 会编译源码，语法错/编码错抛的是别的异常
        raise PluginLoadError(f"{package}: 解析 types.py 失败：{exc}") from exc
    types_module = None
    if spec is not None:
        try:
            types_module = importlib.import_module(f"{package}.types")
        except Exception as exc:
            raise PluginLoadError(f"{package}: 导入 types.py 失败：{exc}") from exc
    if types_module is not None:
        extra = getattr(types_module, "TYPES", None)
        if extra is not None:
            if not isinstance(extra, dict):
                raise PluginLoadError(f"{package}: types.py 的 TYPES 必须是 dict")
            types.update(extra)
    for short in types:
        if not is_name(short):
            raise PluginLoadError(f"{package}: 类型名 {short!r} 不合法（字母开头，含字母数字下划线）")
    return types


def load_plugin(zip_path, loaded_names):
    package = _package_name(zip_path)
    if package in loaded_names:
        raise PluginLoadError(f"插件名重复：{package}（{zip_path.name}）")

    _check_requirements(zip_path, package)
    module = _import_components(zip_path, package)

    name = getattr(module, "PLUGIN_NAME", None)
    if not is_name(name):
        raise PluginLoadError(f"{zip_path.name}: PLUGIN_NAME 缺失或不合法：{name!r}")
    if name != package:
        raise PluginLoadError(
            f"{zip_path.name}: PLUGIN_NAME（{name}）必须与 zip 内目录名（{package}）一致"
        )
    version = getattr(module, "PLUGIN_VERSION", None)
    if not is_version(version):
        raise PluginLoadError(f"{zip_path.name}: PLUGIN_VERSION 缺失或不合法：{version!r}")
    title = getattr(module, "PLUGIN_TITLE", "") or name

    components = getattr(module, "COMPONENTS", None)
    if not isinstance(components, (list, tuple)) or not components:
        raise PluginLoadError(f"{zip_path.name}: COMPONENTS 必须是非空列表")

    return PluginInfo(
        name=name,
        version=version,
        title=str(title),
        types=_collect_types(module, package),
        components=list(components),
        source=str(zip_path),
    )
