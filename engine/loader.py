"""插件目录的发现、校验与加载。

插件结构（契约 §2.1）：

    plugins/                  # 插件根：挂上 sys.path 的单位
    └─ school_bean/           # 插件 = 子目录，目录名 == PLUGIN_NAME
       ├─ __init__.py          # 必须
       ├─ components.py        # 必须，只做声明：PLUGIN_* 常量 + COMPONENTS 清单
       ├─ types.py             # 可选：TYPES = {"短类型名": "说明"}
       ├─ requirements.txt     # 可选：依赖清单，启动时检查是否已安装
       └─ ...                  # 任意子目录 / 源文件 / 数据文件

没有 ``components.py`` 的子目录不是插件（进 skipped）；插件根下的文件（含
``*.zip``）不是插件候选，扫描时直接忽略，不留兼容分支。
"""

import importlib
import importlib.metadata
import importlib.util
import re
import sys
from dataclasses import dataclass, field
from importlib.machinery import PathFinder
from pathlib import Path

from .errors import PluginLoadError, PluginNameConflict
from .typeid import is_name, is_version

_REQ_SPLIT = re.compile(r"[<>=!~\[; ]")

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "plugins"

# importlib.metadata 每次查询都会扫一遍 sys.path，按发行名缓存一次结果。
# 只扫非插件路径：依赖检查看的是引擎自身的运行环境，插件根既不是发行版目录、
# 也不该被反复扫。
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


def scan_plugin_root(plugins_dir):
    """扫描一个插件根，返回 (plugin_dirs, not_plugins)；根不存在返回 None。

    plugin_dirs 是含 ``components.py`` 的子目录；not_plugins 是 [(path, reason)]：
    没有 ``components.py`` 的子目录——它们不是插件，记 skipped，不报错。
    根下的**文件**（含 ``*.zip``）不参与扫描：zip 只是传输格式，不是加载格式。
    """
    root = Path(plugins_dir)
    if not root.is_dir():
        print(f"[警告] 插件目录不存在，已跳过：{root.resolve()}", file=sys.stderr)
        return None
    plugin_dirs = []
    not_plugins = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if (entry / "components.py").is_file():
            plugin_dirs.append(entry)
        else:
            not_plugins.append((entry, f"{entry.name}: 没有 components.py，不当作插件"))
    return plugin_dirs, not_plugins


_MOUNTED = set()


def unmount_plugins():
    sys.path[:] = [p for p in sys.path if p not in _MOUNTED]
    _MOUNTED.clear()


def _mount(path):
    path = str(Path(path).resolve())
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)
    _MOUNTED.add(path)


def add_all_to_sys_path(plugin_roots):
    """把所有插件根统一挂上 sys.path，再逐个 import。

    倒序插入让先给的根排在 sys.path 最前：跨根同名包时先给的根胜出
    （同名本来就报冲突，这里只是让报错前实际加载的代码也确定性）。
    """
    unmount_plugins()
    for root in reversed(plugin_roots):
        _mount(root)


def _is_importable_top_level(name):
    spec = PathFinder.find_spec(name)
    return spec is not None and spec.loader is not None


def _check_structure(plugin_dir):
    """每个含 .py 的目录都必须有 __init__.py，防止半个包静默加载失败。"""
    if not (plugin_dir / "__init__.py").is_file():
        raise PluginLoadError(f"{plugin_dir.name}: 缺少 __init__.py")
    for py_file in sorted(plugin_dir.rglob("*.py")):
        directory = py_file.parent
        if directory == plugin_dir:
            continue
        if not (directory / "__init__.py").is_file():
            raise PluginLoadError(
                f"{plugin_dir.name}: 目录 {directory.relative_to(plugin_dir).as_posix()}/ 缺少 __init__.py"
            )


def _check_requirements(plugin_dir, package):
    """requirements.txt 里的依赖没装就报错，不自动安装。"""
    req = plugin_dir / "requirements.txt"
    if not req.is_file():
        return
    text = req.read_text(encoding="utf-8")

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
            f"{plugin_dir.name}: 缺少依赖 {', '.join(sorted(set(missing)))}，"
            f"请先安装：pip install {' '.join(sorted(set(missing)))}"
        )


def _purge_modules(package):
    """同进程重复加载同名插件前，先清掉旧模块。

    否则 sys.modules 会直接复用旧代码：改了源码再 load 拿到的还是旧类，
    甚至另一个根的同名插件会被第一个根的内容静默顶掉。
    """
    stale = [n for n in sys.modules if n == package or n.startswith(package + ".")]
    for name in stale:
        del sys.modules[name]


def _import_components(package):
    _purge_modules(package)
    # FileFinder 会缓存源码目录的文件清单，不失效会读到旧文件。
    importlib.invalidate_caches()
    try:
        return importlib.import_module(f"{package}.components")
    except Exception as exc:  # 插件自己的导入错误要原样带出来
        raise PluginLoadError(f"{package}: 导入 {package}.components 失败：{exc}") from exc


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


def load_plugin(plugin_dir, loaded_names):
    """导入并校验一个插件目录；插件根必须已挂上 sys.path（Registry.load 负责挂）。"""
    package = plugin_dir.name
    if package in loaded_names:
        previous = loaded_names.get(package)
        source = getattr(previous, "source", "")
        if not source or source.startswith("<"):
            source = "已加载的插件"
        else:
            source = str(Path(source).resolve())
        raise PluginNameConflict(
            f"插件名重复：{package}（{source} 与 {Path(plugin_dir).resolve()}）"
        )

    _check_requirements(plugin_dir, package)
    module = _import_components(package)

    name = getattr(module, "PLUGIN_NAME", None)
    if not is_name(name):
        raise PluginLoadError(f"{plugin_dir.name}: PLUGIN_NAME 缺失或不合法：{name!r}")
    if name != package:
        raise PluginLoadError(
            f"{plugin_dir.name}: PLUGIN_NAME（{name}）必须与目录名（{package}）一致"
        )
    version = getattr(module, "PLUGIN_VERSION", None)
    if not is_version(version):
        raise PluginLoadError(f"{plugin_dir.name}: PLUGIN_VERSION 缺失或不合法：{version!r}")
    title = getattr(module, "PLUGIN_TITLE", "") or name
    if not isinstance(title, str):
        raise PluginLoadError(
            f"{plugin_dir.name}: PLUGIN_TITLE 必须是字符串，实际 {type(title).__name__}"
        )

    components = getattr(module, "COMPONENTS", None)
    if not isinstance(components, (list, tuple)) or not components:
        raise PluginLoadError(f"{plugin_dir.name}: COMPONENTS 必须是非空列表")

    return PluginInfo(
        name=name,
        version=version,
        title=str(title),
        types=_collect_types(package),
        components=list(components),
        source=str(Path(plugin_dir).resolve()),
    )
