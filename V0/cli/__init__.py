"""La línea de comandos del compilador: pedir, mostrar y devolver un código.

Es la mitad que NO es el compilador. Aquí se decide qué se pide (``argparse``),
cómo se ve (``report``) y con qué código termina el proceso; el trabajo lo
hace :mod:`driver`, que no sabe que existe una terminal.

La frontera importa por suriniX: ``suri run --args`` será otro consumidor del
MISMO driver, con su propio parser y su propia presentación. Que hoy la CLI
sea el único no debe hacerla la dueña — por eso la compilación no pasa por
aquí, solo su presentación.

    cli/args.py    la definición de las banderas
    cli/report.py  cómo se imprime (hechos a stdout, diagnósticos a stderr)
"""

from __future__ import annotations

import json
import sys

from config import compilerconfig
from driver import (EXIT_MISSING_DEPENDENCY, EXIT_OK, CompileOptions,
                    compile_source, execute, finish_report)
from driver import inspect as driver_inspect

from .args import build_parser
from .report import (TerminalReporter, print_file_not_found, print_result,
                     print_times)


def _cmd_lang_info() -> int:
    from include.lang_info import build_language_info
    print(json.dumps(build_language_info(), ensure_ascii=False, indent=2))
    return EXIT_OK


def _cmd_init_config() -> int:
    try:
        compilerconfig.ensure_dependencies(required={"pyyaml"})
        path = compilerconfig.generate_config()
    except compilerconfig.DependencyError as exc:
        print(exc, file=sys.stderr)
        return EXIT_MISSING_DEPENDENCY
    print(f"configuracion generada en: {path}")
    return EXIT_OK


def _cmd_extensions(source: str | None) -> int:
    payload, status = driver_inspect.emit_extensions(source)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return status


def _cmd_stage(source: str, stage: str, *, from_stdin: bool) -> int:
    status, mensaje = driver_inspect.emit_stage(
        source, stage, from_stdin=from_stdin)
    if mensaje:
        print(mensaje, file=sys.stderr)
    return status


def _cmd_diagnostics(source: str, *, from_stdin: bool) -> int:
    payload = driver_inspect.emit_diagnostics(source, from_stdin=from_stdin)
    print(json.dumps(payload, ensure_ascii=False))
    # exit 0 aunque haya diagnosticos: el cliente los lee del JSON, no del
    # codigo de salida (distingue 'compilo con errores' de 'el proceso fallo').
    return EXIT_OK


def _cmd_compile(args) -> int:
    """Compilar y —si el target lo pide— ejecutar.

    El orden es el que hace legible la salida: primero todo lo que dijo la
    compilación, luego lo que imprima el programa. Es una decisión de la CLI,
    no del pipeline: por eso ``compile_source`` deja ``should_run`` puesto y
    no lanza nada por su cuenta.
    """
    options = CompileOptions(
        emit_ast_json=args.emit_ast_json, emit_tokens=args.emit_tokens,
        emit_hir=args.emit_hir, hir_pretty=args.hir_pretty,
        dump_symbols=args.dump_symbols, hir_text=args.hir_text,
        run=args.run, debug=args.debug,
        collect_times=args.show_times or args.debug,
        trace_exec=args.trace_exec, trace_memory=args.trace_memory,
    )
    reporter = TerminalReporter()
    result = compile_source(args.source, options, reporter=reporter)

    from driver import EXIT_FILE_NOT_FOUND
    if result.status == EXIT_FILE_NOT_FOUND:
        print_file_not_found(args.source)
        return result.status

    print_result(result)
    exit_code = execute(result, trace_exec=args.trace_exec,
                        trace_memory=args.trace_memory, reporter=reporter)

    if options.collect_times:
        print_times(result)
    report_file = finish_report(result)
    if report_file:
        print(f"reporte de depuracion en: {report_file}", file=sys.stderr)
    return exit_code


def main(argv: list[str]) -> int:
    """Punto de entrada de la línea de comandos."""
    parser = build_parser()
    args = parser.parse_args(argv[1:])

    if args.emit_lang_info:
        return _cmd_lang_info()
    if args.check:
        return compilerconfig._print_report()
    if args.init_config:
        return _cmd_init_config()
    # el descubrimiento se ancla al proyecto, no a un archivo: se puede pedir
    # sin fuente (raiz = CWD), como '--check'.
    if args.emit_extensions:
        return _cmd_extensions(args.source)
    if not args.source:
        parser.print_help()
        return EXIT_OK
    if args.emit_stage:
        return _cmd_stage(args.source, args.emit_stage,
                          from_stdin=args.from_stdin)
    if args.emit_diagnostics:
        return _cmd_diagnostics(args.source, from_stdin=args.from_stdin)
    return _cmd_compile(args)


__all__ = ["main", "build_parser"]
