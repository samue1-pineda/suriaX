#!/usr/bin/env python3
"""Runner de pruebas de suriaX (propio, sin framework externo).

Descubre y ejecuta los tests de las 6 categorías del proyecto:

    unit · grammar · negative_tests · snapshot · e2e · fuzz

``grammar`` cubre la gramática regla a regla en tres niveles (forma del AST,
código de error exacto, y ejecución de punta a punta) para que un fallo se
localice sin leer el resto del pipeline.

**Todas** las pruebas del repositorio viven bajo ``test/``, y este es el único
comando que las corre. Junto a las seis categorías hay dos carpetas que NO lo
son y por eso no se descubren solas:

    test/web/     la suite del backend web (TypeScript). La engancha
                  ``unit/test_web_backend.py``, que la ejecuta con
                  ``node --test``: sigue habiendo un solo comando.
    test/manual/  utilidades que se corren a mano, no en cada corrida.

Cada categoría es una carpeta junto a este archivo. Un test es un módulo con
funciones ``test_*`` (sin argumentos) que lanzan ``AssertionError`` al fallar.
Si una carpeta está vacía, el runner lo informa y sale con 0.

Uso:
    python test/main.py                  # ejecuta todas las categorías
    python test/main.py unit fuzz        # solo categorías indicadas
    python test/main.py --json out.json  # + resumen legible por máquina

``--json`` existe para la CI: escribe el recuento y la LISTA DE FALLOS con su
traza, que es lo que el workflow convierte en la medalla y en el informe del
job. Sin él habría que re-parsear la salida de consola, que está pensada para
una persona y cambia cuando se mejora un mensaje.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import traceback

# raíz del repo en sys.path para que los tests importen el compilador (V0/).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_V0 = os.path.join(_REPO_ROOT, "V0")
for p in (_REPO_ROOT, _V0):
    if p not in sys.path:
        sys.path.insert(0, p)

CATEGORIES = ["unit", "grammar", "negative_tests", "snapshot", "e2e", "fuzz"]


def _discover(category: str) -> list[str]:
    """Rutas de los módulos ``test_*.py`` de una categoría."""
    folder = os.path.join(os.path.dirname(__file__), category)
    if not os.path.isdir(folder):
        return []
    return [
        os.path.join(folder, f)
        for f in sorted(os.listdir(folder))
        if f.startswith("test_") and f.endswith(".py")
    ]


def _run_module(path: str, category: str, failures: list) -> tuple[int, int]:
    """Importa un módulo de test y ejecuta sus funciones ``test_*``.

    Devuelve (pasados, fallidos) y acumula en ``failures`` el detalle de cada
    fallo, que es lo que la CI necesita para decir QUÉ no pasó.
    """
    name = os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    passed = failed = 0
    for attr in dir(module):
        if not attr.startswith("test_"):
            continue
        fn = getattr(module, attr)
        if not callable(fn):
            continue
        try:
            fn()
            passed += 1
            print(f"    ✓ {attr}")
        except Exception as exc:  # noqa: BLE001 - un fallo no detiene los demás
            failed += 1
            print(f"    ✗ {attr}")
            traceback.print_exc()
            failures.append({
                "category": category,
                "module": name,
                "test": attr,
                # la primera línea del error: lo que cabe en una tabla del
                # resumen. La traza completa ya está en el log del job.
                "error": f"{exc.__class__.__name__}: {exc}".strip().splitlines()[0][:300],
            })
    return passed, failed


def run_tests(categories: list[str] | None = None,
              json_path: str | None = None) -> int:
    selected = categories or CATEGORIES
    total_pass = total_fail = total_mods = 0
    failures: list = []

    for category in selected:
        if category not in CATEGORIES:
            print(f"[aviso] categoría desconocida: {category}")
            continue
        modules = _discover(category)
        print(f"== {category} ({len(modules)} módulos) ==")
        for path in modules:
            total_mods += 1
            p, f = _run_module(path, category, failures)
            total_pass += p
            total_fail += f

    print()
    if total_mods == 0:
        print("no hay tests aún. ver test/tests_to_add.txt para el plan de pruebas.")
        return 0

    print(f"resultado: {total_pass} pasados, {total_fail} fallidos "
          f"({total_mods} módulos).")

    if json_path:
        _write_summary(json_path, total_pass, total_fail, total_mods,
                       selected, failures)
    return 1 if total_fail else 0


def _write_summary(path: str, passed: int, failed: int, modules: int,
                   categories: list, failures: list) -> None:
    """Resumen de la corrida en JSON (para la CI)."""
    carpeta = os.path.dirname(os.path.abspath(path))
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({
            "passed": passed,
            "failed": failed,
            "total": passed + failed,
            "modules": modules,
            "categories": categories,
            "failures": failures,
        }, fh, ensure_ascii=False, indent=2)


def _parse_args(argv: list[str]) -> tuple[list[str] | None, str | None]:
    """``[categorías...] [--json RUTA]``. Sin argparse: son dos opciones."""
    categorias: list[str] = []
    json_path = None
    resto = list(argv)
    while resto:
        arg = resto.pop(0)
        if arg == "--json":
            if not resto:
                print("--json necesita una ruta", file=sys.stderr)
                raise SystemExit(2)
            json_path = resto.pop(0)
        elif arg.startswith("--json="):
            json_path = arg.split("=", 1)[1]
        else:
            categorias.append(arg)
    return (categorias or None), json_path


if __name__ == "__main__":
    _cats, _json = _parse_args(sys.argv[1:])
    raise SystemExit(run_tests(_cats, _json))
