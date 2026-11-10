"""Claude Desktop extension entry point: the bundle root is on sys.path, so the
vendored server4 package imports directly."""

from server4.cli import main

main()
