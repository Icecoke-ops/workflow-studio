"""列名检查与配置取值的解析。"""

import json


def require_columns(data, columns):
    missing = [column for column in columns if column not in data.columns]
    if missing:
        raise ValueError(f"列不存在：{missing}（可用：{list(data.columns)}）")


def parse_json_value(text):
    """把配置里的字符串按 JSON 解析成标量或数组；不是合法 JSON 就当纯文本。

    # ponytail: 引擎的 json 类型不收标量，所以这里用 string + JSON 解析；第三个组件需要时把本函数提到 engine.api
    """
    try:
        return json.loads(text)
    except ValueError:
        return text
