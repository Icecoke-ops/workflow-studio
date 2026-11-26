"""本地 Web API 后端：给 Vue 前端提供插件查询、校验和执行接口。"""

__version__ = "0.6.2"

# 绑定端口失败的退出码：launcher 靠它判断「这次起不来值得重试」
BIND_FAILED_EXIT = 3

__all__ = ["__version__", "BIND_FAILED_EXIT"]
