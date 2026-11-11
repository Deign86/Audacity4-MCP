"""Console entry point.

Dispatches the setup subcommands before importing server4.main, which
registers every tool at import time - `audacity4-mcp install` should not
spend a second loading 159 tool schemas it never uses.
"""

import sys

SUBCOMMANDS = ("install", "uninstall", "doctor", "print-config", "enable-bridge", "-h", "--help")


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in SUBCOMMANDS:
        from server4.installer import cli

        sys.exit(cli(args))

    # A bare word that is not a subcommand is a typo (or two commands pasted
    # onto one line). Starting the stdio server would just hang waiting for a
    # client, so say what went wrong instead.
    if args and not args[0].startswith("-"):
        sys.stderr.write(
            f"audacity4-mcp: unknown command {args[0]!r}. "
            f"Commands: {', '.join(c for c in SUBCOMMANDS if not c.startswith('-'))}. "
            "Run with no arguments to start the MCP server.\n"
        )
        sys.exit(2)

    from server4.main import main as run_server

    run_server()


if __name__ == "__main__":
    main()
