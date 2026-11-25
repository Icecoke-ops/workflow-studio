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
from importlib.machinery import PathFinder
from pathlib import Path

from . import stdtypes
from .errors import PluginLoadError, PluginNameConflict
from .typeid import is_name, is_version

_REQ_SPLIT = re.compile(r"[<>=!~\[; ]")

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "plugins"

# importlib.metadata 每次查询都会扫一遍 sys.path，按发行名缓存一次结果。
# 查询时必须排除已挂载的插件 zip：CPython 3.12 的 FastPath 会为 zip 路径缓存
# 打开的 ZipFile（进程内不释放），Windows 上表现为插件 zip 被锁住、无法重建。
_INSTALLED = {}
_SCANNED = False
_SCAN_FAILED = False


def _dist_key(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _scan_installed():
    """一次性索引已安装的发行版，只扫非插件路径（原因见上）。

    METADATA 里没有 Name 的畸形发行版直接跳过：pip 装的必然带 Name，
    不为人为构造的输入加兜底。
    """
    global _SCANNED, _SCAN_FAILED
    paths = [p for p in sys.path if isinstance(p, str) and p not in _MOUNTED]
    try:
        for candidate in importlib.metadata.distributions(path=paths):
            try:
                name = candidate.metadata["Name"]
                if name:
                    _INSTALLED.setdefault(_dist_key(name), candidate.version)
            except Exception:
                continue
    except Exception as exc:
        # 失败不标记已扫描，下次调用重试；警告只打一次。
        if not _SCAN_FAILED:
            _SCAN_FAILED = True
            print(f"[警告] 依赖清单扫描失败：{exc}", file=sys.stderr)
        return
    _SCANNED = True


def _installed_version(dist):
    if not _SCANNED:
        _scan_installed()
    return _INSTALLED.get(_dist_key(dist))


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
        print(f"[警告] 插件目录不存在，已跳过：{path.resolve()}", file=sys.stderr)
        return []
    return sorted(path.glob("*.zip"))


_MOUNTED = set()


def unmount_plugins():
    for path in list(_MOUNTED):
        while path in sys.path:
            sys.path.remove(path)
    _MOUNTED.clear()


def _mount(path):
    path = str(Path(path).resolve())
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)
    _MOUNTED.add(path)


def add_all_to_sys_path(zip_paths):
    """先把所有插件 zip 挂上 sys.path，再逐个 import。

    这样插件之间互相 import 就不受文件名顺序影响（B 依赖 A 时，
    A 是否排在前面不该决定成败）。
    """
    unmount_plugins()
    for zip_path in zip_paths:
        _mount(zip_path)


def unmount_plugin(zip_path):
    """摘下单个插件 zip（宽容模式跳过坏包时用，别让残留路径影响后续加载）。"""
    path = str(Path(zip_path).resolve())
    while path in sys.path:
        sys.path.remove(path)
    _MOUNTED.discard(path)


def _is_importable_top_level(name):
    spec = PathFinder.find_spec(name)
    return spec is not None and spec.loader is not None


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

    root_importable = [
        n for n in names if "/" not in n and n.endswith((".py", ".pyc", ".pyo"))
    ]
    if root_importable:
        raise PluginLoadError(
            f"{zip_path.name}: 源码/字节码必须放在 {package}/ 目录下，"
            f"发现根目录文件 {root_importable}"
        )

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
        if dist != line:
            print(
                f"[警告] 插件 {package} 的依赖 {line} 只检查是否已安装，不校验版本",
                file=sys.stderr,
            )
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
    _mount(zip_path)
    _purge_modules(package)
    importlib.invalidate_caches()
    try:
        return importlib.import_module(f"{package}.components")
    except Exception as exc:  # 插件自己的导入错误要原样带出来
        raise PluginLoadError(f"{zip_path.name}: 导入 {package}.components 失败：{exc}") from exc


def _collect_types(package):
    types = {}
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
        previous = loaded_names.get(package) if hasattr(loaded_names, "get") else None
        source = getattr(previous, "source", "")
        if not source or source.startswith("<"):
            source = "已加载的插件"
        else:
            source = str(Path(source).resolve())
        raise PluginNameConflict(
            f"插件名重复：{package}（{source} 与 {Path(zip_path).resolve()}）"
        )

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
    if not isinstance(title, str):
        raise PluginLoadError(
            f"{zip_path.name}: PLUGIN_TITLE 必须是字符串，实际 {type(title).__name__}"
        )

    components = getattr(module, "COMPONENTS", None)
    if not isinstance(components, (list, tuple)) or not components:
        raise PluginLoadError(f"{zip_path.name}: COMPONENTS 必须是非空列表")

    return PluginInfo(
        name=name,
        version=version,
        title=str(title),
        types=_collect_types(package),
        components=list(components),
        source=str(zip_path),
    )
