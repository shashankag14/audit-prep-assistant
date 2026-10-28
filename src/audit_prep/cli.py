"""Command-line entry point. The pipeline is added stage by stage; see README."""

import sys

from audit_prep import __version__


def main(argv: list[str] | None = None) -> int:
    print(f"audit-prep {__version__}: pipeline not built yet")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
