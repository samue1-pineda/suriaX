#!/usr/bin/env python3
"""CLI del intérprete de suriaX — hoy: lector/validador de ``.phir``.

Punto de entrada del protobuf hacia el intérprete (Fase 5.5, paso 1 de
``ARQUITECTURA.md`` secc. 13). Lee el HIR que emitió el frontend
(``python V0/main.py programa.srcx --emit-hir``), valida su esquema
fail-fast y muestra qué contiene — sin ejecutarlo todavía (el tree-walk
llega en los pasos siguientes del plan).

Uso:
    python runtime/interpreter/main.py dumps/programa.srcx.phir
    python runtime/interpreter/main.py programa.phir --text   # + texto protobuf
"""

from __future__ import annotations

import argparse
import os
import sys

# rutas de import: la raiz del repo y V0/ (para 'src.HIR.stubs'), igual que
# V0/main.py — este entrypoint es el unico puente, el resto del paquete
# interpreter asume los paths ya montados.
_HERE = os.path.abspath(os.path.dirname(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_V0_ROOT = os.path.join(_REPO_ROOT, "V0")
for _p in (_REPO_ROOT, _V0_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from runtime.interpreter import loader  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="suriaX-interp",
        description="Intérprete de suriaX (hoy: lector/validador del HIR .phir).",
    )
    parser.add_argument("phir", help="archivo .phir emitido por el frontend (--emit-hir)")
    parser.add_argument(
        "--text", action="store_true",
        help="imprime además el Module completo en formato de texto protobuf "
             "(el árbol crudo: para depurar el FORMATO)",
    )
    parser.add_argument(
        "--pretty", action="store_true",
        help="imprime el HIR en su vista LEGIBLE: una línea por sentencia, "
             "expresiones con su tipo resuelto y la posición del fuente al "
             "margen. Es la forma de leer un .phir que ya existe",
    )
    parser.add_argument(
        "--exec", action="store_true", dest="execute",
        help="liga las unidades (main + librerías) y EJECUTA la función de "
             "entrada con el tree-walk",
    )
    parser.add_argument(
        "--test", action="store_true", dest="run_tests",
        help="ejecuta los bloques 'test \"...\" { }' del módulo principal",
    )
    parser.add_argument(
        "--entry", default=None, metavar="FN",
        help="función de entrada (por defecto 'interpreter.entry' del yaml, "
             "o 'main')",
    )
    parser.add_argument(
        "--trace-memory", action="store_true",
        help="traza las instrucciones de memoria (&, move, free) al ejecutar",
    )
    parser.add_argument(
        "--trace-exec", action="store_true",
        help="traza la ejecucion (llamadas y retornos, con anidamiento)",
    )
    args = parser.parse_args(argv[1:])

    if not os.path.isfile(args.phir):
        print(f"archivo no encontrado: {args.phir}", file=sys.stderr)
        return 2

    if args.execute or args.run_tests:
        from runtime.interpreter import interpreter as interp
        try:
            image = loader.load_image(args.phir)
        except loader.HIRLoadError as exc:
            print(f"error cargando HIR: {exc}", file=sys.stderr)
            return 3
        # config minima de la CLI directa; V0/main.py pasa la del yaml via
        # este mismo camino (mismos knobs, una sola forma).
        config = {"interpreter": {
            "entry": args.entry or "main",
            "trace_memory": args.trace_memory,
            "trace_exec": args.trace_exec,
            "max_steps": 0,
        }}
        if args.run_tests:
            return interp.run_tests(image, config)
        return interp.run(image, config)

    try:
        module = loader.load_module(args.phir)
    except loader.HIRLoadError as exc:
        print(f"error cargando HIR: {exc}", file=sys.stderr)
        return 3

    print(loader.summarize(module))
    hooks = loader.index_hooks(module)
    print(f"  (hooks indexados para despacho O(1): {len(hooks)})")
    if module.libraries:
        refs = ", ".join(f"{r.alias} ({r.phir})" for r in module.libraries)
        print(f"  unidades referenciadas: {refs}")

    if args.pretty:
        import sys as _sys
        from V0.src.HIR.pretty import write_pretty
        print("\n--- HIR (vista legible) ---")
        write_pretty(module, _sys.stdout)

    if args.text:
        from V0.src.HIR.emmit_IR import module_to_text
        print("\n--- Module (texto protobuf) ---")
        print(module_to_text(module))

    print("\nHIR válido. Ejecuta con --exec (tree-walk + instrucciones de memoria).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
