#!/usr/bin/env python3
"""Runner de pruebas de suriaX (propio, sin framework externo).

Descubre y ejecuta los tests de las 6 categorías del proyecto:

    unit · grammar · negative_tests · snapshot · e2e · fuzz

``grammar`` cubre la gramática regla a regla en tres niveles (forma del AST,
código de error exacto, y ejecución de punta a punta) para que un fallo se
localice sin leer el resto del pipeline.

Cada categoría es una carpeta junto a este archivo. Un test es un módulo con
funciones ``test_*`` (sin argumentos) que lanzan ``AssertionError`` al fallar.

Hoy el plan de pruebas está documentado en ``test/tests_to_add.txt`` pero las
carpetas pueden estar vacías; en ese caso el runner lo informa y sale con 0.

Uso:
    python test/main.py            # ejecuta todas las categorías
    python test/main.py unit fuzz  # solo categorías indicadas
"""

from __future__ import annotations

import importlib.util
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


def _run_module(path: str) -> tuple[int, int]:
    """Importa un módulo de test y ejecuta sus funciones ``test_*``.

    Devuelve (pasados, fallidos).
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
        except Exception:  # noqa: BLE001 - un test fallido no detiene los demás
            failed += 1
            print(f"    ✗ {attr}")
            traceback.print_exc()
    return passed, failed


def run_tests(categories: list[str] | None = None) -> int:
    selected = categories or CATEGORIES
    total_pass = total_fail = total_mods = 0

    for category in selected:
        if category not in CATEGORIES:
            print(f"[aviso] categoría desconocida: {category}")
            continue
        modules = _discover(category)
        print(f"== {category} ({len(modules)} módulos) ==")
        for path in modules:
            total_mods += 1
            p, f = _run_module(path)
            total_pass += p
            total_fail += f

    print()
    if total_mods == 0:
        print("no hay tests aún. ver test/tests_to_add.txt para el plan de pruebas.")
        return 0

    print(f"resultado: {total_pass} pasados, {total_fail} fallidos "
          f"({total_mods} módulos).")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(run_tests(sys.argv[1:] or None))
