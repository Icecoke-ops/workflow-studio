"""本地 Web 服务：launcher（落地页 + 项目进程管理）、项目 API 服务与共享 HTTP 传输层。"""

__version__ = "0.6.2"

# 绑定端口失败的退出码：launcher 靠它判断「这次起不来值得重试」
BIND_FAILED_EXIT = 3

__all__ = ["__version__", "BIND_FAILED_EXIT"]
