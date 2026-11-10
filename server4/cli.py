"""Console entry point.

Dispatches the setup subcommands before importing server4.main, which
registers every tool at import time - `audacity4-mcp install` should not
spend a second loading 159 tool schemas it never uses.
"""

import sys

SUBCOMMANDS = ("install", "uninstall", "doctor", "print-config", "-h", "--help")


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in SUBCOMMANDS:
        from server4.installer import cli

        sys.exit(cli(args))

    from server4.main import main as run_server

    run_server()


if __name__ == "__main__":
    main()
