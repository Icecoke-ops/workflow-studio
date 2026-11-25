import sys

from .server import main

LAUNCHER_NOT_READY = "launcher 尚未实现（批 3），项目服务请用 --serve DIR"

if __name__ == "__main__":
    argv = sys.argv[1:]
    if not any(arg == "--serve" or arg.startswith("--serve=") for arg in argv):
        print(LAUNCHER_NOT_READY, file=sys.stderr)
        sys.exit(1)
    sys.exit(main())
