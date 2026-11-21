"""模型持久化：SaveModel（保存并原样传下去）/ LoadModel（从文件读回）。

模型文件是 pickle（joblib）格式，反序列化会执行文件里的代码，
所以 LoadModel 的 desc 里必须把这条安全提示摆在界面上。
"""

import os
import pickle
import sys

import engine
from engine.api import Component, PredictorModel, expand_env

_MAGIC = "workflow-studio.model"


def _path_schema():
    return {
        "type": "string",
        "title": "模型文件路径",
        "desc": "绝对路径优先；也可写相对路径，按进程工作目录解析，支持 ${变量}",
        "required": True,
    }


def _plugin():
    """惰性取插件声明：components.py 在导入期会导入本模块，模块级导入会循环。"""
    from ml.components import PLUGIN_NAME, PLUGIN_VERSION

    return PLUGIN_NAME, PLUGIN_VERSION


class SaveModel(Component):
    name = "SaveModel"
    title = "保存模型"
    desc = "把模型保存成文件并原样传给下游；模型文件是 pickle 格式，只应加载可信来源的文件"

    @staticmethod
    def config_schema():
        return {"path": _path_schema()}

    @staticmethod
    def input_schema():
        return {
            "model": {"types": ["std_1.0@model"], "required": True, "title": "模型"}
        }

    @staticmethod
    def output_schema():
        return {"model": {"type": "std_1.0@model", "title": "模型"}}

    def __init__(self, config):
        self.path = expand_env(config["path"])

    def invoke(self, model):
        import joblib

        plugin_name, plugin_version = _plugin()
        payload = {
            "magic": _MAGIC,
            "engine": engine.__version__,
            "plugin": plugin_name,
            "plugin_version": plugin_version,
            "class": f"{type(model).__module__}.{type(model).__qualname__}",
            "model": model,
        }
        try:
            joblib.dump(payload, self.path)
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"写入模型失败：{self.path}：{exc}") from exc
        return {"model": model}


class LoadModel(Component):
    name = "LoadModel"
    title = "加载模型"
    desc = (
        "从模型文件读回模型；模型文件是 pickle 格式，反序列化会执行文件里的代码，"
        "只加载可信来源的文件"
    )

    @staticmethod
    def config_schema():
        return {"path": _path_schema()}

    @staticmethod
    def input_schema():
        return {}

    @staticmethod
    def output_schema():
        return {"model": {"type": "std_1.0@model", "title": "模型"}}

    def __init__(self, config):
        self.path = expand_env(config["path"])

    def invoke(self):
        import joblib

        if not os.path.exists(self.path):
            raise ValueError(f"模型文件不存在：{self.path}")
        try:
            payload = joblib.load(self.path)
        except (pickle.UnpicklingError, EOFError, OSError, ImportError) as exc:
            # 文件像模型但读不出来（损坏、截断、缺依赖、无权限）：保留路径和原因
            raise ValueError(f"读取模型失败：{self.path}（{exc}）") from exc
        except Exception as exc:
            # 内容根本不是 pickle（例如随手选了个 JSON）：直接说不是模型文件
            raise ValueError(f"不是模型文件：{self.path}（无法反序列化：{exc}）") from exc
        if not isinstance(payload, dict) or payload.get("magic") != _MAGIC:
            raise ValueError(f"不是模型文件：{self.path}")

        plugin_name, plugin_version = _plugin()
        saved_engine = payload.get("engine")
        saved_version = payload.get("plugin_version")
        if saved_version != plugin_version:
            raise ValueError(
                f"模型插件版本不匹配：该文件由 {payload.get('plugin')} "
                f"v{saved_version} 保存，当前 {plugin_name} v{plugin_version}；"
                f"请用当前版本重新训练并保存"
            )

        model = payload.get("model")
        if not isinstance(model, PredictorModel):
            raise ValueError(
                f"不是模型文件：{self.path}（载入的对象不是 PredictorModel）"
            )
        model_class = f"{type(model).__module__}.{type(model).__qualname__}"
        if payload.get("class") != model_class:
            raise ValueError(
                f"模型类不匹配：该文件记录的是 {payload.get('class')}，"
                f"载入的是 {model_class}；请用当前版本重新训练并保存"
            )

        # 引擎版本只影响行为兼容，不影响 pickle 能否读，按 sklearn 的做法警告后继续
        if saved_engine != engine.__version__:
            print(
                f"[警告] 模型 {self.path} 由引擎 v{saved_engine} 保存，"
                f"当前引擎 v{engine.__version__}；继续加载，"
                f"若预测结果异常请重新训练并保存",
                file=sys.stderr,
            )
        return {"model": model}
