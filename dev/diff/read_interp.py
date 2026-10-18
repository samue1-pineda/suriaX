#!/usr/bin/env python3
"""LECTURA en el intérprete: carga un .phir y liga sus unidades, SIN ejecutar.

Es lo que hace 'runtime/interpreter/main.py --exec' antes de ejecutar
('loader.load_image': decodificar el wire format, validar 'schema_version' y
ligar el programa con sus librerías). Imprime una línea con el número de
unidades para que el arnés compruebe que cargó.

Uso: python dev/diff/read_interp.py dumps/prog.srcx.phir
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_REPO, os.path.join(_REPO, "V0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from runtime.interpreter import loader  # noqa: E402


def main(argv: list) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        image = loader.load_image(argv[1])
    except loader.HIRLoadError as exc:
        print(f"error cargando HIR: {exc}", file=sys.stderr)
        return 3
    print(f"imagen ligada: {1 + len(image.units)} unidad(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
