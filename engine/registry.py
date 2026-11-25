"""插件 / 组件 / 类型注册表。

加载分两遍，插件之间没有加载顺序要求：

1. 导入所有 zip，收集插件元数据和它声明的类型
2. 类型全集就位后，再校验并解析每个组件的 schema
"""

import sys
from dataclasses import dataclass
from pathlib import Path

from . import schema as schema_mod
from . import stdtypes
from .api import Component
from .errors import PluginLoadError, PluginNameConflict, SchemaError, WorkflowError
from .loader import (
    PluginInfo,
    _is_importable_top_level,
    _package_name,
    _purge_modules,
    add_all_to_sys_path,
    find_zips,
    load_plugin,
    unmount_plugin,
    unmount_plugins,
)
from .typeid import qualify, resolve


@dataclass
class ComponentEntry:
    plugin: str
    name: str
    title: str
    desc: str
    cls: type
    config_schema: dict
    input_schema: dict
    output_schema: dict

    @property
    def full_name(self):
        return f"{self.plugin}.{self.name}"


class Registry:
    def __init__(self):
        self.plugins = {}
        self.components = {}
        self.types = {}
        self.models = {}  # 类型标识 -> 必须继承的抽象基类
        self.skipped = []  # 宽容模式跳过 / 未加载的 zip，按扫描顺序

    # -- 加载 ------------------------------------------------------------
    def load(self, *plugins_dirs, strict=True):
        """加载插件目录；``strict=False`` 跳过坏 zip 并记进 ``self.skipped``。

        宽容模式只跳过「这个 zip 不是插件 / 加载不进去」；同名冲突与
        schema 不合法仍然是硬错误（那是真 bug，跳过等于静默降级）。
        """
        self._register_std()
        self.skipped = []
        unmount_plugins()
        zip_paths = []
        seen = set()
        for plugins_dir in plugins_dirs:
            for zip_path in find_zips(plugins_dir):
                absolute = str(Path(zip_path).resolve())
                if absolute in seen:
                    continue
                seen.add(absolute)
                zip_paths.append(zip_path)

        candidates = []
        for zip_path in zip_paths:
            try:
                package = _package_name(zip_path)
            except PluginLoadError as exc:
                if strict:
                    raise
                self._skip(zip_path, exc)
                continue
            # 内置模块的 import 虽然顶不掉，但必须在 _purge_modules 之前拦住：
            # 否则 sys.modules 里的真模块会先被删掉、再重建成残骸（sys 尤其致命）。
            if package in sys.stdlib_module_names or _is_importable_top_level(package):
                message = (
                    f"{zip_path.name}: 插件名 {package!r} 与已安装的模块/标准库同名，"
                    f"会顶掉对它的 import，请换一个名字"
                )
                if strict:
                    raise PluginLoadError(message)
                self._skip(zip_path, message)
                continue
            candidates.append((zip_path, package))

        add_all_to_sys_path([zip_path for zip_path, _ in candidates])
        infos = []
        for zip_path, package in candidates:
            try:
                info = load_plugin(zip_path, self.plugins)
            except PluginNameConflict:
                raise
            except PluginLoadError as exc:
                if strict:
                    raise
                self._skip(zip_path, exc)
                unmount_plugin(zip_path)
                _purge_modules(package)
                continue
            self.plugins[info.name] = info
            infos.append(info)
            for short, desc in info.types.items():
                self.types[qualify(info.name, info.version, short)] = str(desc)
        for info in infos:
            self._register(info)
        return self

    def _skip(self, zip_path, reason):
        self.skipped.append(
            {
                "file": Path(zip_path).name,
                "path": str(Path(zip_path).resolve()),
                "reason": str(reason),
            }
        )

    def _register_std(self):
        """标准类型永远在，不依赖任何插件。"""
        for short, desc in stdtypes.TYPES.items():
            self.types[stdtypes.type_id(short)] = desc
        for short, cls in stdtypes.MODELS.items():
            self.models[stdtypes.type_id(short)] = cls
        self.plugins[stdtypes.PLUGIN_NAME] = PluginInfo(
            name=stdtypes.PLUGIN_NAME,
            version=stdtypes.PLUGIN_VERSION,
            title=stdtypes.PLUGIN_TITLE,
            types=dict(stdtypes.TYPES),
            components=[],
            source="<builtin>",
        )

    def _register(self, info):
        for cls in info.components:
            if not isinstance(cls, type) or not issubclass(cls, Component):
                raise PluginLoadError(
                    f"{info.name}: {cls!r} 不是 engine.api.Component 的子类"
                )
            name = getattr(cls, "name", "")
            if not isinstance(name, str) or not name.isidentifier():
                raise PluginLoadError(f"{info.name}: 组件 name 不合法：{name!r}")
            if (info.name, name) in self.components:
                raise PluginLoadError(f"{info.name}: 组件名重复：{name}")

            where = f"{info.name}.{name}"
            title = getattr(cls, "title", "")
            desc = getattr(cls, "desc", "")
            if not isinstance(title, str):
                raise PluginLoadError(
                    f"{where}: title 必须是字符串，实际 {type(title).__name__}"
                )
            if not isinstance(desc, str):
                raise PluginLoadError(
                    f"{where}: desc 必须是字符串，实际 {type(desc).__name__}"
                )
            abstract = getattr(cls, "__abstractmethods__", None)
            if abstract:
                raise PluginLoadError(
                    f"{where}: 组件类还有未实现的抽象方法 {sorted(abstract)}"
                )
            try:
                config_schema = cls.config_schema()
                input_schema = cls.input_schema()
                output_schema = cls.output_schema()
            except WorkflowError:
                raise
            except Exception as exc:
                raise PluginLoadError(f"{where}: 读取 schema 失败：{exc}") from exc
            schema_mod.check_config_schema(config_schema, f"{where}.config")
            schema_mod.check_input_schema(input_schema, f"{where}.input")
            schema_mod.check_output_schema(output_schema, f"{where}.output")

            self.components[(info.name, name)] = ComponentEntry(
                plugin=info.name,
                name=name,
                title=title or name,
                desc=desc,
                cls=cls,
                config_schema=config_schema,
                input_schema=self._resolve_inputs(input_schema, info, where),
                output_schema=self._resolve_outputs(output_schema, info, where),
            )

    def _resolve_type(self, value, info, where):
        full = resolve(value, info.name, info.version)
        if full in self.types:
            return full
        tail = full.split("@", 1)[-1]
        candidates = sorted(t for t in self.types if t.endswith("@" + tail))
        hint = f"，是不是想写 {' 或 '.join(candidates)}？" if candidates else ""
        if "@" in value:
            raise SchemaError(
                f"{where}: 类型 {full} 未注册"
                f"（写的是全名，说明对应插件没加载或没声明该类型）{hint}"
            )
        raise SchemaError(
            f"{where}: 类型 {full} 未注册"
            f"（短名只能引用本插件在 types.py 里声明的类型；引用别家类型必须写完整标识）{hint}"
        )

    def _resolve_inputs(self, input_schema, info, where):
        resolved = {}
        for port, spec in input_schema.items():
            item = dict(spec)
            item["types"] = [
                self._resolve_type(t, info, f"{where}.input.{port}") for t in spec["types"]
            ]
            item.setdefault("required", True)
            resolved[port] = item
        return resolved

    def _resolve_outputs(self, output_schema, info, where):
        resolved = {}
        for port, spec in output_schema.items():
            item = dict(spec)
            item["type"] = self._resolve_type(
                spec["type"], info, f"{where}.output.{port}"
            )
            resolved[port] = item
        return resolved

    # -- 查询 ------------------------------------------------------------
    def get_component(self, plugin, name):
        return self.components.get((plugin, name))

    def short_type(self, type_id):
        """``std_1.0@table`` -> ``std@table``，给界面显示用。"""
        if "@" not in type_id:
            return type_id
        head, name = type_id.split("@", 1)
        plugin = head.rsplit("_", 1)[0]
        return f"{plugin}@{name}"
