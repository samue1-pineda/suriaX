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
from driver import (EXIT_INTERNAL_ERROR, EXIT_MISSING_DEPENDENCY, EXIT_OK,
                    CompileOptions, compile_source, execute, finish_report)
from driver import inspect as driver_inspect
from error_handler.InternalCompilerError import InternalCompilerError

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


def _cmd_index(source: str, *, from_stdin: bool) -> int:
    payload = driver_inspect.emit_index(source, from_stdin=from_stdin)
    print(json.dumps(payload, ensure_ascii=False))
    return EXIT_OK   # como '--emit-diagnostics': lo que importa va en el JSON


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
                        trace_memory=args.trace_memory, reporter=reporter,
                        argumentos=[args.source,
                                    *getattr(args, "argumentos_del_programa", [])])

    if options.collect_times:
        print_times(result)
    report_file = finish_report(result)
    if report_file:
        print(f"reporte de depuracion en: {report_file}", file=sys.stderr)
    return exit_code


def main(argv: list[str]) -> int:
    """Punto de entrada de la línea de comandos.

    Un fallo DEL COMPILADOR no sale como traceback suelto con exit 1 (que se
    lee "tu programa tiene errores"): se muestra al estilo de Python —traza
    de la excepción original, y luego código, fase y archivo— y el proceso
    termina con ``EXIT_INTERNAL_ERROR`` (6).
    """
    parser = build_parser()
    # 'suri prog.srcx -- a b c': lo que va después del primer '--' es del
    # PROGRAMA, no del compilador. Se separa antes de parsear para que una
    # bandera del programa ('-- --verbose') no la interprete argparse.
    propios, del_programa = _separar_argumentos(argv[1:])
    args = parser.parse_args(normalizar_run(propios))
    args.argumentos_del_programa = del_programa
    try:
        return _despachar(parser, args)
    except InternalCompilerError as ice:
        print(ice.render(), file=sys.stderr)
        return EXIT_INTERNAL_ERROR
    except Exception as exc:  # noqa: BLE001 - se reporta como ICE, nunca se traga
        # un fallo fuera del driver (un comando de consulta, el formato de la
        # salida): la fase es el comando que se estaba atendiendo.
        ice = InternalCompilerError.desde(exc, phase=_comando(args),
                                          file=args.source)
        print(ice.render(), file=sys.stderr)
        return EXIT_INTERNAL_ERROR


def normalizar_run(argv: list[str]) -> list[str]:
    """'--run compiler' -> '--run=compiler', y '--run' solo -> '--run='.

    '--run' lleva un valor OPCIONAL, y con argparse eso se come lo que venga
    detras: 'suri --run prog.srcx' tomaria 'prog.srcx' por el motor. Aqui
    solo se juntan los dos valores que existen; cualquier otra cosa queda
    como estaba.
    """
    salida: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--run":
            if i + 1 < len(argv) and argv[i + 1] in ("compiler", "interpreter"):
                salida.append("--run=" + argv[i + 1])
                i += 2
                continue
            salida.append("--run=")
        else:
            salida.append(argv[i])
        i += 1
    return salida


def _separar_argumentos(argv: list[str]) -> tuple[list[str], list[str]]:
    """(argumentos del compilador, argumentos del programa)."""
    if "--" not in argv:
        return list(argv), []
    corte = argv.index("--")
    return list(argv[:corte]), list(argv[corte + 1:])


def _comando(args) -> str:
    """Nombre legible del comando que atendía la CLI (para un ICE)."""
    for bandera in ("emit_lang_info", "check", "init_config", "emit_extensions",
                    "emit_stage", "emit_diagnostics", "emit_index"):
        if getattr(args, bandera, None):
            return "cli --" + bandera.replace("_", "-")
    return "cli (compilar)"


def _despachar(parser, args) -> int:
    """Atiende el comando pedido y devuelve el código de salida."""
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
    if args.emit_index:
        return _cmd_index(args.source, from_stdin=args.from_stdin)
    return _cmd_compile(args)


__all__ = ["main", "build_parser"]
