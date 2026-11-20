"""参数 schema 与端口 schema 的格式定义、自检和取值校验。

config schema 每个参数项：
    {"type": "string|integer|number|boolean|enum|json|array",
     "title": "显示名", "desc": "说明",
     "required": bool, "default": 任意,
     "min": 数字, "max": 数字, "step": 数字,
     "choices": [{"value": ..., "label": ...} | 标量],
     "pattern": "正则"}

输入端口 schema：
    {"端口名": {"types": ["std_1.0@table", ...], "required": bool,
                "title": "显示名", "desc": "说明"}}

输出端口 schema：
    {"端口名": {"type": "std_1.0@table", "title": ..., "desc": ...}}
"""

import copy
import re

from .errors import SchemaError

CONFIG_TYPES = ("string", "integer", "number", "boolean", "enum", "json", "array")
CONFIG_KEYS = {
    "type", "title", "desc", "required", "default",
    "min", "max", "step", "choices", "pattern",
}
INPUT_KEYS = {"types", "required", "title", "desc"}
OUTPUT_KEYS = {"type", "title", "desc"}


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _choice_values(spec):
    values = []
    for item in spec.get("choices") or []:
        values.append(item["value"] if isinstance(item, dict) else item)
    return values


def _same_scalar(left, right):
    """True 与 1 在 Python 里相等，但作为枚举候选项应当区分开。"""
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


def _hint(spec):
    title = spec.get("title")
    return f"（{title}）" if title else ""


# --------------------------------------------------------------------------
# 插件作者写错 schema：直接抛错，不让它进到运行时
# --------------------------------------------------------------------------

def check_config_schema(schema, where):
    if not isinstance(schema, dict):
        raise SchemaError(f"{where}: 参数 schema 必须是 dict")
    for name, spec in schema.items():
        w = f"{where}.{name}"
        if not isinstance(name, str) or not name.isidentifier():
            raise SchemaError(f"{where}: 参数名 {name!r} 必须是合法标识符")
        if not isinstance(spec, dict):
            raise SchemaError(f"{w}: 参数描述必须是 dict")
        unknown = set(spec) - CONFIG_KEYS
        if unknown:
            raise SchemaError(f"{w}: 未知字段 {sorted(unknown)}")
        kind = spec.get("type")
        if kind not in CONFIG_TYPES:
            raise SchemaError(f"{w}: type 必须是 {CONFIG_TYPES} 之一，实际 {kind!r}")
        if "required" in spec and not isinstance(spec["required"], bool):
            raise SchemaError(f"{w}: required 必须是布尔值")
        for key in ("min", "max", "step"):
            value = spec.get(key)
            if value is None:
                continue
            if not _is_number(value):
                raise SchemaError(f"{w}: {key} 必须是数字")
            if kind not in ("integer", "number", "array"):
                raise SchemaError(f"{w}: type={kind} 不支持 {key}")
        low, high = spec.get("min"), spec.get("max")
        if low is not None and high is not None and low > high:
            raise SchemaError(f"{w}: min({low}) 不能大于 max({high})")
        if kind == "enum":
            choices = spec.get("choices")
            if not isinstance(choices, list) or not choices:
                raise SchemaError(f"{w}: type=enum 必须提供非空 choices 数组")
            for item in choices:
                if isinstance(item, dict):
                    if "value" not in item:
                        raise SchemaError(f"{w}: choices 每项为 dict 时必须带 value")
                elif not isinstance(item, (str, int, float, bool)):
                    raise SchemaError(f"{w}: choices 每项必须是标量或 {{value,label}}")
        elif spec.get("choices") is not None:
            raise SchemaError(f"{w}: 只有 type=enum 才能声明 choices")
        pattern = spec.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str):
                raise SchemaError(f"{w}: pattern 必须是字符串")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise SchemaError(f"{w}: pattern 不是合法正则：{exc}") from exc
        if "default" in spec:
            problems = _check_value(spec, spec["default"], f"{w}(default)")
            if problems:
                raise SchemaError("；".join(problems))


def check_input_schema(schema, where):
    if not isinstance(schema, dict):
        raise SchemaError(f"{where}: 输入 schema 必须是 dict")
    for name, spec in schema.items():
        w = f"{where}.{name}"
        if not isinstance(name, str) or not name.isidentifier():
            raise SchemaError(f"{w}: 输入端口名必须是合法标识符")
        if not isinstance(spec, dict):
            raise SchemaError(f"{w}: 端口描述必须是 dict")
        unknown = set(spec) - INPUT_KEYS
        if unknown:
            raise SchemaError(f"{w}: 未知字段 {sorted(unknown)}")
        types = spec.get("types")
        if not isinstance(types, list) or not types:
            raise SchemaError(f"{w}: types 必须是非空数组")
        for item in types:
            if not isinstance(item, str) or not item.strip():
                raise SchemaError(f"{w}: types 里每项必须是非空字符串")
        if "required" in spec and not isinstance(spec["required"], bool):
            raise SchemaError(f"{w}: required 必须是布尔值")


def check_output_schema(schema, where):
    if not isinstance(schema, dict):
        raise SchemaError(f"{where}: 输出 schema 必须是 dict")
    for name, spec in schema.items():
        w = f"{where}.{name}"
        if not isinstance(name, str) or not name.isidentifier():
            raise SchemaError(f"{w}: 输出端口名必须是合法标识符")
        if not isinstance(spec, dict):
            raise SchemaError(f"{w}: 端口描述必须是 dict")
        unknown = set(spec) - OUTPUT_KEYS
        if unknown:
            raise SchemaError(f"{w}: 未知字段 {sorted(unknown)}")
        kind = spec.get("type")
        if not isinstance(kind, str) or not kind.strip():
            raise SchemaError(f"{w}: type 必须是非空字符串")


# --------------------------------------------------------------------------
# 节点取值校验
# --------------------------------------------------------------------------

def fill_defaults(schema, values):
    """按 schema 补齐默认值，返回新 dict。

    可变默认值必须深拷贝，否则多个节点会共享同一个 list/dict，互相污染。
    """
    filled = {}
    for name, spec in schema.items():
        if name in values:
            filled[name] = values[name]
        elif "default" in spec:
            default = spec["default"]
            filled[name] = copy.deepcopy(default) if isinstance(default, (dict, list)) else default
    return filled


def check_config_values(schema, values, where):
    """返回错误字符串列表（不抛异常，便于一次报全）。"""
    if not isinstance(values, dict):
        return [f"{where}: config 必须是 JSON 对象"]

    errors = []
    unknown = set(values) - set(schema)
    if unknown:
        errors.append(f"{where}: 未知参数 {sorted(unknown)}")
    for name, spec in schema.items():
        w = f"{where}.{name}"
        if name not in values:
            if spec.get("required") and "default" not in spec:
                errors.append(f"{w}: 缺少必填参数{_hint(spec)}")
            continue
        errors.extend(_check_value(spec, values[name], w))
    return errors


def _check_value(spec, value, where):
    errors = []
    kind = spec.get("type")

    if kind == "string":
        if not isinstance(value, str):
            errors.append(f"{where}: 需要字符串，实际 {type(value).__name__}")
        else:
            pattern = spec.get("pattern")
            if pattern and not re.search(pattern, value):
                errors.append(f"{where}: 值 {value!r} 不匹配 {pattern}")
    elif kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"{where}: 需要整数，实际 {type(value).__name__}")
    elif kind == "number":
        if not _is_number(value):
            errors.append(f"{where}: 需要数字，实际 {type(value).__name__}")
    elif kind == "boolean":
        if not isinstance(value, bool):
            errors.append(f"{where}: 需要布尔值，实际 {type(value).__name__}")
    elif kind == "enum":
        allowed = _choice_values(spec)
        if not any(_same_scalar(value, item) for item in allowed):
            errors.append(f"{where}: {value!r} 不在候选项 {allowed} 中")
    elif kind == "json":
        if not isinstance(value, (dict, list)):
            errors.append(f"{where}: json 类型需要对象或数组，实际 {type(value).__name__}")
    elif kind == "array":
        if not isinstance(value, list):
            errors.append(f"{where}: array 类型需要数组，实际 {type(value).__name__}")

    if errors:
        return errors

    low, high = spec.get("min"), spec.get("max")
    if kind in ("integer", "number"):
        if low is not None and value < low:
            errors.append(f"{where}: {value} 小于最小值 {low}")
        if high is not None and value > high:
            errors.append(f"{where}: {value} 大于最大值 {high}")
    elif kind == "array":
        if low is not None and len(value) < low:
            errors.append(f"{where}: 元素个数 {len(value)} 小于最小值 {low}")
        if high is not None and len(value) > high:
            errors.append(f"{where}: 元素个数 {len(value)} 大于最大值 {high}")
    return errors
