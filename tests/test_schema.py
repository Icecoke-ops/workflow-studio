"""engine.schema 参数 / 端口 schema 校验测试。

直接运行：python tests/test_schema.py
"""

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import schema as schema_mod
from engine.errors import SchemaError
from engine.registry import Registry

from _harness import check, expect_raises, run_cases


def expect_errors(schema, values, *fragments):
    errors = schema_mod.check_config_values(schema, values, "cfg")
    text = "；".join(errors)
    for fragment in fragments:
        check(fragment in text, f"错误信息缺少 {fragment!r}，实际错误：{errors}")
    return errors


def expect_no_errors(schema, values):
    errors = schema_mod.check_config_values(schema, values, "cfg")
    check(not errors, f"不应该报错，实际：{errors}")


def expect_schema_error(fn, *fragments):
    return expect_raises(SchemaError, fn, *fragments)


# --------------------------------------------------------------------------
# 节点取值校验
# --------------------------------------------------------------------------

def case_integer_rejects():
    schema = {"n": {"type": "integer"}}
    expect_errors(schema, {"n": 1.5}, "需要整数")
    expect_errors(schema, {"n": True}, "需要整数")
    expect_errors(schema, {"n": "3"}, "需要整数")
    expect_no_errors(schema, {"n": 3})


def case_number_rejects_bool():
    schema = {"x": {"type": "number"}}
    expect_errors(schema, {"x": True}, "需要数字")
    expect_errors(schema, {"x": "1.2"}, "需要数字")
    expect_no_errors(schema, {"x": 1.2})
    expect_no_errors(schema, {"x": 3})


def case_boolean_and_string():
    expect_errors({"b": {"type": "boolean"}}, {"b": 1}, "需要布尔值")
    expect_errors({"b": {"type": "boolean"}}, {"b": "true"}, "需要布尔值")
    expect_no_errors({"b": {"type": "boolean"}}, {"b": False})
    expect_errors({"s": {"type": "string"}}, {"s": 1}, "需要字符串")
    expect_errors(
        {"s": {"type": "string", "pattern": "^a+$"}}, {"s": "bbb"}, "不匹配"
    )
    expect_no_errors({"s": {"type": "string", "pattern": "^a+$"}}, {"s": "aaa"})


def case_enum():
    schema = {"mode": {"type": "enum", "choices": ["a", "b"]}}
    expect_errors(schema, {"mode": "c"}, "不在候选项")
    expect_no_errors(schema, {"mode": "a"})
    labeled = {"mode": {"type": "enum", "choices": [{"value": 1, "label": "一"}]}}
    expect_errors(labeled, {"mode": 2}, "不在候选项")
    expect_no_errors(labeled, {"mode": 1})


def case_enum_bool_int_distinct():
    """enum 候选项里 true 和 1 不是同一个值。"""
    schema = {"v": {"type": "enum", "choices": [1]}}
    expect_errors(schema, {"v": True}, "不在候选项")
    expect_no_errors(schema, {"v": 1})

    schema = {"v": {"type": "enum", "choices": [True]}}
    expect_errors(schema, {"v": 1}, "不在候选项")
    expect_no_errors(schema, {"v": True})


def case_min_max():
    expect_errors({"n": {"type": "integer", "min": 10}}, {"n": 5}, "小于最小值 10")
    expect_errors({"n": {"type": "integer", "max": 100}}, {"n": 101}, "大于最大值 100")
    expect_errors({"x": {"type": "number", "min": 0}}, {"x": -0.5}, "小于最小值 0")
    expect_no_errors({"n": {"type": "integer", "min": 0, "max": 10}}, {"n": 10})
    expect_errors(
        {"xs": {"type": "array", "min": 2}}, {"xs": [1]}, "元素个数 1 小于最小值 2"
    )
    expect_errors(
        {"xs": {"type": "array", "max": 1}}, {"xs": [1, 2]}, "元素个数 2 大于最大值 1"
    )


def case_json_array_types():
    expect_errors({"j": {"type": "json"}}, {"j": "x"}, "需要对象或数组")
    expect_no_errors({"j": {"type": "json"}}, {"j": {"a": 1}})
    expect_no_errors({"j": {"type": "json"}}, {"j": [1]})
    expect_errors({"a": {"type": "array"}}, {"a": {"x": 1}}, "需要数组")
    expect_no_errors({"a": {"type": "array"}}, {"a": []})


def case_required_and_unknown():
    schema = {
        "need": {"type": "string", "required": True},
        "opt": {"type": "string"},
    }
    expect_errors(schema, {}, "缺少必填参数")
    expect_no_errors(schema, {"need": "x"})
    expect_errors(schema, {"need": "x", "typo": 1}, "未知参数")
    expect_errors(schema, {"need": "x", "typo": 1}, "typo")


def case_required_with_default_not_missing():
    schema = {"n": {"type": "integer", "required": True, "default": 5}}
    expect_no_errors(schema, {})


def case_values_not_dict():
    expect_errors({"n": {"type": "integer"}}, [], "config 必须是 JSON 对象")


def case_fill_defaults():
    schema = {
        "a": {"type": "integer", "default": 1},
        "b": {"type": "string", "required": True},
    }
    filled = schema_mod.fill_defaults(schema, {"b": "x"})
    check(filled.get("a") == 1, f"默认值没填上：{filled}")
    check(filled.get("b") == "x", f"显式值被改掉：{filled}")


def case_mutable_defaults_deep_copied():
    schema = {
        "xs": {"type": "array", "default": [1, 2]},
        "obj": {"type": "json", "default": {"k": 1}},
    }
    first = schema_mod.fill_defaults(schema, {})
    second = schema_mod.fill_defaults(schema, {})
    check(first["xs"] == [1, 2] and second["xs"] == [1, 2], f"list 默认值不对：{first}")
    check(first["xs"] is not second["xs"], "两次 fill_defaults 不应共享同一个 list 对象")
    check(first["obj"] is not second["obj"], "两次 fill_defaults 不应共享同一个 dict 对象")

    first["xs"].append(3)
    first["obj"]["k"] = 2
    check(second["xs"] == [1, 2], f"改一个节点的 list 影响了另一个：{second['xs']}")
    check(second["obj"] == {"k": 1}, f"改一个节点的 dict 影响了另一个：{second['obj']}")
    check(schema["xs"]["default"] == [1, 2], "不应污染 schema 里的 list 默认值")
    check(schema["obj"]["default"] == {"k": 1}, "不应污染 schema 里的 dict 默认值")


# --------------------------------------------------------------------------
# 插件作者写错 schema：加载时就该抛 SchemaError
# --------------------------------------------------------------------------

def case_config_schema_definition_errors():
    expect_schema_error(lambda: schema_mod.check_config_schema([], "p"), "必须是 dict")
    expect_schema_error(
        lambda: schema_mod.check_config_schema({"a": "x"}, "p"), "参数描述必须是 dict"
    )
    expect_schema_error(
        lambda: schema_mod.check_config_schema({"1bad": {"type": "string"}}, "p"),
        "必须是合法标识符",
    )
    expect_schema_error(
        lambda: schema_mod.check_config_schema(
            {"a": {"type": "string", "bogus": 1}}, "p"
        ),
        "未知字段",
    )
    expect_schema_error(
        lambda: schema_mod.check_config_schema({"a": {"type": "interger"}}, "p"),
        "type 必须是",
    )
    expect_schema_error(
        lambda: schema_mod.check_config_schema(
            {"a": {"type": "string", "required": "yes"}}, "p"
        ),
        "required 必须是布尔值",
    )
    expect_schema_error(
        lambda: schema_mod.check_config_schema(
            {"a": {"type": "integer", "min": "1"}}, "p"
        ),
        "min 必须是数字",
    )


def case_enum_schema_definition_errors():
    expect_schema_error(
        lambda: schema_mod.check_config_schema({"a": {"type": "enum"}}, "p"),
        "必须提供非空 choices",
    )
    expect_schema_error(
        lambda: schema_mod.check_config_schema(
            {"a": {"type": "enum", "choices": []}}, "p"
        ),
        "必须提供非空 choices",
    )
    expect_schema_error(
        lambda: schema_mod.check_config_schema(
            {"a": {"type": "enum", "choices": [{"label": "x"}]}}, "p"
        ),
        "必须带 value",
    )
    expect_schema_error(
        lambda: schema_mod.check_config_schema(
            {"a": {"type": "string", "choices": ["x"]}}, "p"
        ),
        "只有 type=enum 才能声明 choices",
    )


def case_pattern_and_default_definition_errors():
    expect_schema_error(
        lambda: schema_mod.check_config_schema(
            {"a": {"type": "string", "pattern": "["}}, "p"
        ),
        "不是合法正则",
    )
    expect_schema_error(
        lambda: schema_mod.check_config_schema(
            {"a": {"type": "integer", "default": "abc"}}, "p"
        ),
        "需要整数",
    )


def case_valid_config_schema_passes():
    schema = {
        "n": {"type": "integer", "title": "数", "default": 1, "min": 0},
        "s": {"type": "string", "pattern": "^a"},
        "e": {"type": "enum", "choices": [{"value": "x", "label": "X"}]},
        "j": {"type": "json"},
    }
    schema_mod.check_config_schema(schema, "p")


def case_input_schema_errors():
    expect_schema_error(lambda: schema_mod.check_input_schema([], "p"), "必须是 dict")
    expect_schema_error(
        lambda: schema_mod.check_input_schema({"1bad": {"types": ["t"]}}, "p"),
        "必须是合法标识符",
    )
    expect_schema_error(
        lambda: schema_mod.check_input_schema({"a": {"types": ["t"], "bogus": 1}}, "p"),
        "未知字段",
    )
    expect_schema_error(
        lambda: schema_mod.check_input_schema({"a": {}}, "p"), "types 必须是非空数组"
    )
    expect_schema_error(
        lambda: schema_mod.check_input_schema({"a": {"types": []}}, "p"),
        "types 必须是非空数组",
    )
    expect_schema_error(
        lambda: schema_mod.check_input_schema({"a": {"types": [1]}}, "p"),
        "必须是非空字符串",
    )
    expect_schema_error(
        lambda: schema_mod.check_input_schema(
            {"a": {"types": ["t"], "required": 1}}, "p"
        ),
        "required 必须是布尔值",
    )
    schema_mod.check_input_schema({"a": {"types": ["t"], "required": False}}, "p")


def case_output_schema_errors():
    expect_schema_error(lambda: schema_mod.check_output_schema([], "p"), "必须是 dict")
    expect_schema_error(
        lambda: schema_mod.check_output_schema({"1bad": {"type": "t"}}, "p"),
        "必须是合法标识符",
    )
    expect_schema_error(
        lambda: schema_mod.check_output_schema({"a": {"type": "t", "bogus": 1}}, "p"),
        "未知字段",
    )
    expect_schema_error(
        lambda: schema_mod.check_output_schema({"a": {}}, "p"),
        "type 必须是非空字符串",
    )
    expect_schema_error(
        lambda: schema_mod.check_output_schema({"a": {"type": 1}}, "p"),
        "type 必须是非空字符串",
    )
    schema_mod.check_output_schema({"a": {"type": "t"}}, "p")


# --------------------------------------------------------------------------
# 加载时校验：临时插件把 schema 写错，Registry.load 要抛 SchemaError
# --------------------------------------------------------------------------

_BAD_PLUGIN_SOURCE = '''\
from engine.api import Component

PLUGIN_NAME = "%(name)s"
PLUGIN_VERSION = "1.0"
PLUGIN_TITLE = "坏 schema"


class Bad(Component):
    name = "Bad"

    @staticmethod
    def config_schema():
        return %(schema)s

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {}

    def __init__(self, config):
        pass

    def invoke(self):
        return {}


COMPONENTS = [Bad]
'''


def load_bad_plugin(name, schema_text):
    """在临时目录打一个坏插件 zip，加载它。"""
    source = _BAD_PLUGIN_SOURCE % {"name": name, "schema": schema_text}
    with tempfile.TemporaryDirectory(prefix="engine_schema_test_") as tmp:
        zip_path = Path(tmp) / f"{name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{name}/__init__.py", "")
            archive.writestr(f"{name}/components.py", source)
        Registry().load(tmp)


def case_bad_schema_type_at_load():
    expect_schema_error(
        lambda: load_bad_plugin("sbad1", '{"p": {"type": "interger"}}'), "type 必须是"
    )


def case_enum_without_choices_at_load():
    expect_schema_error(
        lambda: load_bad_plugin("sbad2", '{"p": {"type": "enum"}}'),
        "必须提供非空 choices",
    )


def case_bad_default_at_load():
    expect_schema_error(
        lambda: load_bad_plugin("sbad3", '{"p": {"type": "integer", "default": "abc"}}'),
        "需要整数",
    )


def case_min_greater_than_max_at_load():
    expect_schema_error(
        lambda: load_bad_plugin("sbad4", '{"p": {"type": "integer", "min": 10, "max": 1}}'),
        "不能大于 max",
    )


def case_string_with_min_at_load():
    expect_schema_error(
        lambda: load_bad_plugin("sbad5", '{"p": {"type": "string", "min": 1}}'),
        "不支持 min",
    )


CASES = [
    ("integer 拒绝 1.5 / bool / \"3\"", case_integer_rejects),
    ("number 拒绝 bool", case_number_rejects_bool),
    ("boolean / string 类型与 pattern", case_boolean_and_string),
    ("enum 候选项校验", case_enum),
    ("enum 区分 bool 与 int", case_enum_bool_int_distinct),
    ("min / max 越界", case_min_max),
    ("json / array 类型", case_json_array_types),
    ("required 缺失与未知参数", case_required_and_unknown),
    ("required + default 不报缺失", case_required_with_default_not_missing),
    ("config 不是对象", case_values_not_dict),
    ("默认值填充", case_fill_defaults),
    ("可变默认值深拷贝", case_mutable_defaults_deep_copied),
    ("config schema 定义错误", case_config_schema_definition_errors),
    ("enum schema 定义错误", case_enum_schema_definition_errors),
    ("pattern / default 定义错误", case_pattern_and_default_definition_errors),
    ("合法 config schema 通过", case_valid_config_schema_passes),
    ("input schema 定义错误", case_input_schema_errors),
    ("output schema 定义错误", case_output_schema_errors),
    ("加载时抛 SchemaError：type 拼错", case_bad_schema_type_at_load),
    ("加载时抛 SchemaError：enum 无 choices", case_enum_without_choices_at_load),
    ("加载时抛 SchemaError：default 不合法", case_bad_default_at_load),
    ("加载时抛 SchemaError：min 大于 max", case_min_greater_than_max_at_load),
    ("加载时抛 SchemaError：string 配 min", case_string_with_min_at_load),
]


def main():
    return run_cases("schema", CASES)


if __name__ == "__main__":
    sys.exit(main())
