"""``python -m suri`` — la misma entrada que el ejecutable instalado."""

import sys

from .command import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
