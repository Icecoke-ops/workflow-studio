import sys

if __name__ == "__main__":
    argv = sys.argv[1:]
    if any(arg == "--serve" or arg.startswith("--serve=") for arg in argv):
        from .server import main
    else:
        from .launcher import main
    sys.exit(main())
