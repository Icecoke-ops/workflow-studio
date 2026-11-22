"""执行钩子：事件表 + 分发器。

引擎只认事件名和每个事件回读哪些字段；具体钩子逻辑一个都不在这里，
都在工程同级的 ``hooks/<名字>/`` 下，通过 ``install(ctx)`` 注册。

钩子回调统一 ``fn(data, execution) -> None``：**原地改 data 生效**，
引擎在回调返回后只回读 :data:`EVENTS` 里声明的字段，返回值不用。
"""

import importlib.util
import sys
import uuid
from pathlib import Path

from .errors import HookError, RunAborted

# 事件名 -> 回调返回后引擎回读的 data 字段（空元组 = 只读）
EVENTS = {
    "plugins_loaded": (),
    "workflow_loaded": ("workflow",),
    "env_ready": ("env",),
    "node_create_before": ("config",),
    "node_create_after": (),
    "node_invoke_before": ("inputs",),
    "node_end": ("outputs",),
    "run_end": (),
}


class HookContext:
    """钩子注册表 + 分发器，``install(ctx)`` 拿到的就是它。"""

    def __init__(self):
        self.handlers = {}  # 事件名 -> [回调]
        self.execution = None  # 节点实例全部建好之后才填上
        self.serve = None  # 钩子可选定义 serve(execution)，由它驱动整轮

    def on(self, event, callback):
        """注册回调；事件名拼错直接报错，不许静默失效。"""
        if event not in EVENTS:
            raise HookError(
                f"未知事件名 {event!r}，合法事件：{'、'.join(EVENTS)}"
            )
        self.handlers.setdefault(event, []).append(callback)

    def emit(self, event, data):
        """依次调用该事件的回调，返回回读字段组成的 dict。

        回调前字段类型就不对（例如工作流 JSON 本身不是对象）归调用方校验；
        只有回调把它改成非对象才报 HookError。
        """
        fields = EVENTS[event]
        before = {key: data.get(key) for key in fields}
        for callback in self.handlers.get(event, ()):
            try:
                callback(data, self.execution)
            except Exception as exc:
                raise RunAborted(f"钩子回调（{event}）抛出异常：{exc}") from exc
        try:
            readback = {key: data[key] for key in fields}
        except (KeyError, TypeError) as exc:
            raise HookError(
                f"钩子回调（{event}）改坏了回读字段 {exc}，"
                f"必须保留：{'、'.join(fields)}"
            ) from exc
        for key, value in readback.items():
            if not isinstance(value, dict) and isinstance(before[key], dict):
                raise HookError(
                    f"钩子回调（{event}）把 {key} 改成了 "
                    f"{type(value).__name__}，必须是对象"
                )
        return readback


def load(path):
    """加载钩子并调用它的 ``install(ctx)``，返回填好的 :class:`HookContext`。

    路径是目录：有 ``hook.py`` 就加载它；没有但有 ``__init__.py`` 就按 Python
    包加载（支持 ``from .xxx import ...``，可以拆多文件）；是文件：直接加载。
    """
    directory = Path(path)
    if directory.is_dir():
        single = directory / "hook.py"
        if single.is_file():
            module = _load_file(single)
        elif (directory / "__init__.py").is_file():
            module = _load_package(directory)
        else:
            raise HookError(
                f"钩子目录 {directory.resolve()} 里既没有 hook.py 也没有 __init__.py"
            )
    elif directory.is_file():
        module = _load_file(directory)
    else:
        raise HookError(f"钩子路径不存在：{directory.resolve()}")

    install = getattr(module, "install", None)
    if not callable(install):
        _purge(module)
        raise HookError(f"{path}：钩子模块必须定义 install(ctx)")
    context = HookContext()
    try:
        install(context)
    except Exception as exc:
        _purge(module)
        raise HookError(f"{path}：install() 失败：{exc}") from exc
    serve = getattr(module, "serve", None)
    context.serve = serve if callable(serve) else None
    return context


def _purge(module):
    """失败路径把模块和它的子模块从 sys.modules 清掉，避免反复加载时累积。"""
    prefix = module.__name__
    for name in [n for n in sys.modules if n == prefix or n.startswith(prefix + ".")]:
        del sys.modules[name]


def _load_file(file_path):
    spec = importlib.util.spec_from_file_location("_engine_hook", file_path)
    if spec is None or spec.loader is None:
        raise HookError(f"无法加载钩子模块：{file_path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise HookError(f"钩子模块 {file_path} 导入失败：{exc}") from exc
    return module


def _load_package(directory):
    """按包加载：唯一前缀名避免同名钩子互相顶掉，子模块靠包的 __path__ 找。"""
    name = f"_engine_hook_{uuid.uuid4().hex[:8]}"
    init = directory / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        name, init, submodule_search_locations=[str(directory)]
    )
    if spec is None or spec.loader is None:
        raise HookError(f"无法加载钩子包：{directory}")
    module = importlib.util.module_from_spec(spec)
    # 相对导入（from .xxx import ...）要求父包已经在 sys.modules 里
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        _purge(module)
        raise HookError(f"钩子包 {directory} 导入失败：{exc}") from exc
    return module
