#!/usr/bin/env python3
"""Script de prueba del lexer de suriaX.

Pipeline que ejercita:

    archivo .srcx  ->  source_reader (UTF-8 -> str)  ->  Lexer (tokens)
                   ->  Parser.run_test_directive  (#test lexer -> volcado)

Uso:
    python run_lexer.py [archivo.srcx]

Si no se pasa archivo, usa ``sample.srcx`` que esta junto a este script.

Comportamiento:
 - si el archivo empieza con la directiva ``#test lexer``, el parser vuelca el
   arreglo de tokens a consola (via ``__repr__``).
 - si NO empieza con esa directiva, este script vuelca los tokens igualmente
   (modo "dump directo") para que el archivo siga siendo util como prueba.
 - los errores lexicos recuperables se listan al final con su codigo LEXxxx.
"""

from __future__ import annotations

import os
import sys

# permitir ejecutar el script directamente: anadir la raiz del paquete (V0)
# a sys.path para que 'src', 'include' y 'error_handler' sean importables.
_V0_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _V0_ROOT not in sys.path:
    sys.path.insert(0, _V0_ROOT)

from src.frontend.lexer import source_reader          # noqa: E402
from src.frontend.lexer.lexer import Lexer            # noqa: E402
from src.frontend.parser.parser import Parser         # noqa: E402


def main(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else os.path.join(
        os.path.dirname(__file__), "sample.srcx"
    )

    if not os.path.isfile(path):
        print(f"archivo no encontrado: {path}", file=sys.stderr)
        return 2

    # 1. decodificacion UTF-8 -> str (fase previa al lexer)
    source = source_reader.read_file(path)

    # 2. lexer -> list[Token]
    lexer = Lexer(source, file=path)
    tokens = lexer.tokenize()

    # 3. parser: orquesta la directiva #test lexer
    parser = Parser(tokens)
    executed = parser.run_test_directive()

    if executed is None:
        # el archivo no pidio #test lexer; volcamos igual para la prueba.
        print(f"=== dump directo  ({len(tokens)} tokens) ===")
        for i, tok in enumerate(tokens):
            print(f"[{i:>3}] {tok!r}")

    # 4. reporte de errores lexicos recuperados
    if lexer.errors:
        print("\n=== errores lexicos ===")
        for err in lexer.errors:
            print(f"  {err.code}: {err.message}  ({err.loc})")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
