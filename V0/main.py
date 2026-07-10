#!/usr/bin/env python3
"""Entrypoint (CLI) del compilador suriaX.

Estado actual (Pre-Alpha): el unico pipeline funcional es el **front-end
lexico**. Este comando:

    1. verifica las dependencias que la fase actual necesita;
    2. decodifica el ``.srcx`` a Unicode (``source_reader``);
    3. lo tokeniza (``Lexer``);
    4. si el archivo empieza con ``#test lexer`` vuelca los tokens via el
       parser; si no, los vuelca en modo directo.

A futuro este mismo entrypoint orquestara el pipeline completo
(lexer -> parser -> AST -> HIR -> MIR -> LLVM-22 -> nativo/wASM), leyendo la
configuracion de ``.suriaX_config.yaml``. Ver ``how_to_run.md``.

Uso:
    python V0/main.py archivo.srcx
    python V0/main.py --check          # solo verifica dependencias
    python V0/main.py --init-config     # genera .suriaX_config.yaml
"""

from __future__ import annotations

import argparse
import os
import sys

# permitir 'python V0/main.py ...' desde cualquier cwd: la raiz del paquete (V0)
# debe estar en sys.path para importar 'src', 'include', 'error_handler'.
_V0_ROOT = os.path.abspath(os.path.dirname(__file__))
if _V0_ROOT not in sys.path:
    sys.path.insert(0, _V0_ROOT)

import config.compilerconfig as compilerconfig  # noqa: E402
from src.frontend.lexer import source_reader  # noqa: E402
from src.frontend.lexer.lexer import Lexer  # noqa: E402
from src.frontend.parser.parser import Parser  # noqa: E402

# dependencias que la fase actual (solo lexer) realmente necesita.
# el lexer no usa LLVM/protobuf/pybind11; basta con poder leer el archivo.
_PHASE_DEPS: set[str] = set()


def _run_source(path: str) -> int:
    if not os.path.isfile(path):
        print(f"archivo no encontrado: {path}", file=sys.stderr)
        return 2

    # 1. dependencias de la fase actual (hoy: ninguna obligatoria para lexar)
    try:
        compilerconfig.ensure_dependencies(required=_PHASE_DEPS)
    except compilerconfig.DependencyError as exc:
        print(exc, file=sys.stderr)
        return 3

    # 2. decodificacion UTF-8 -> str
    source = source_reader.read_file(path)

    # 3. lexer -> list[Token]
    lexer = Lexer(source, file=path)
    tokens = lexer.tokenize()

    # 4. parser: orquesta la directiva #test lexer (volcado de tokens)
    parser = Parser(tokens)
    executed = parser.run_test_directive()
    if executed is None:
        print(f"=== tokens  ({len(tokens)}) ===")
        for i, tok in enumerate(tokens):
            print(f"[{i:>3}] {tok!r}")

    # 5. reporte de errores lexicos recuperados
    if lexer.errors:
        print("\n=== errores lexicos ===", file=sys.stderr)
        for err in lexer.errors:
            print(f"  {err.code}: {err.message}  ({err.loc})", file=sys.stderr)
        return 1

    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="suriaX",
        description="Compilador suriaX (Pre-Alpha: solo front-end lexico).",
    )
    parser.add_argument("source", nargs="?", help="archivo .srcx a procesar")
    parser.add_argument(
        "--check", action="store_true",
        help="verifica las dependencias del compilador y termina",
    )
    parser.add_argument(
        "--init-config", action="store_true",
        help="genera un .suriaX_config.yaml por defecto y termina",
    )
    args = parser.parse_args(argv[1:])

    if args.check:
        return compilerconfig._print_report()

    if args.init_config:
        try:
            compilerconfig.ensure_dependencies(required={"pyyaml"})
            path = compilerconfig.generate_config()
        except compilerconfig.DependencyError as exc:
            print(exc, file=sys.stderr)
            return 3
        print(f"configuracion generada en: {path}")
        return 0

    if not args.source:
        parser.print_help()
        return 0

    return _run_source(args.source)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
