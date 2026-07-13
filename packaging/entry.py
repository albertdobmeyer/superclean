"""PyInstaller entry point.

PyInstaller freezes a script, not a console_scripts entry point, so this is the
one-line shim that stands in for the `superclean` script the wheel installs.
"""
import sys

from superclean.cli import main

if __name__ == "__main__":
    sys.exit(main())
