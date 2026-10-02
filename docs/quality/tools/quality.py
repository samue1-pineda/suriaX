"""Punto de entrada de las automatizaciones de calidad.

    python docs/quality/tools/quality.py all            # todo (lento: minutos a horas)
    python docs/quality/tools/quality.py python         # PEP 8 / 20 / 257
    python docs/quality/tools/quality.py cpp            # Core Guidelines, cppcheck
    python docs/quality/tools/quality.py sanitizers     # ASan y UBSan sobre la VM
    python docs/quality/tools/quality.py portability    # dependencias del sistema operativo
    python docs/quality/tools/quality.py suite          # la suite, como medida
    python docs/quality/tools/quality.py coverage       # cobertura de la suite
    python docs/quality/tools/quality.py report         # solo regenerar los documentos

Opciones: ``--build-dir DIR`` (el compile_commands.json para clang-tidy),
``--only asan|ubsan`` (sanitizers), ``--categories c1,c2`` (suite y coverage).

Cada medición guarda su JSON en ``docs/quality/reports/`` y al final se
regeneran los documentos de ``docs/quality/cumplimiento/`` con TODO lo medido
hasta ahora (lo que nunca se midió aparece como NO MEDIDO).

Esto NO es la suite de pruebas ni corre con ella: se usa en los lotes que
cambian varias fases del compilador a la vez (ver docs/quality/README.md).
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common  # noqa: E402

MEASUREMENTS = ["python", "cpp", "portability", "suite", "sanitizers", "coverage"]


def _measure(name: str, args: argparse.Namespace) -> None:
    started = time.perf_counter()
    print(f"== {name} ==", flush=True)
    categories = args.categories.split(",") if args.categories else None
    if name == "python":
        import python_checks

        data = python_checks.measure()
    elif name == "cpp":
        import cpp_checks

        data = cpp_checks.measure(args.build_dir)
    elif name == "portability":
        import portability

        data = {}
        for scope_name, scope in (("compiler", common.PY_SCOPE), ("tests", common.PY_TESTS)):
            files = list(portability.iter_python_files(scope))
            findings = [f for path in files for f in portability.scan_file(path)]
            data[scope_name] = {
                "files": len(files),
                "clean_files": len({common.rel(p) for p in files} - {f.file for f in findings}),
                "findings": [vars(f) for f in findings],
            }
            data[scope_name]["clean_pct"] = common.percent(
                data[scope_name]["clean_files"], len(files)
            )
    elif name == "suite":
        import suite_checks

        data = suite_checks.run_suite(categories)
    elif name == "sanitizers":
        import sanitizers

        data = sanitizers.measure([args.only] if args.only else None)
    elif name == "coverage":
        import suite_checks

        data = suite_checks.coverage(categories)
    else:
        raise SystemExit(f"medición desconocida: {name}")
    path = common.save_report(name, data)
    print(f"   -> {common.rel(path)} ({time.perf_counter() - started:.0f} s)", flush=True)


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(
        prog="quality.py", description="Mide la calidad del compilador (docs/quality)."
    )
    parser.add_argument("what", nargs="+", choices=["all", "report", *MEASUREMENTS])
    parser.add_argument(
        "--build-dir",
        default=None,
        help="build con compile_commands.json (por defecto, el primero)",
    )
    parser.add_argument(
        "--only", choices=["asan", "ubsan"], default=None, help="con 'sanitizers': solo uno"
    )
    parser.add_argument(
        "--categories",
        default=None,
        help="con 'suite'/'coverage': categorías separadas por comas " "(por defecto --todo)",
    )
    args = parser.parse_args(argv)
    todo = MEASUREMENTS if "all" in args.what else [w for w in args.what if w != "report"]
    for name in todo:
        _measure(name, args)
    import report

    for path in report.generate():
        print(f"documento: {common.rel(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
