#!/usr/bin/env python3
"""Entrypoint (CLI) del compilador

La configuración y las salidas viven en el paquete ``config/`` de la raíz
del repo (orquestador ``config/compilerconfig.py``); el frontend
(``V0/src/frontend/``) NO depende de ese paquete — este entrypoint es el
único puente.

ejemplos de uso:
    python V0/main.py archivo.srcx
    python V0/main.py archivo.srcx --emit-ast-json --emit-tokens
    python V0/main.py --check          # solo verifica dependencias
    python V0/main.py --init-config     # genera .suriaX_config.yaml
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional

#Se agregan las rutas del paquete V0 y de la raíz del repositorio para que
#los módulos puedan importarse tanto cuando se ejecuta este archivo desde la carpeta V0 como desde la raíz del proyecto
_V0_ROOT = os.path.abspath(os.path.dirname(__file__))
_REPO_ROOT = os.path.dirname(_V0_ROOT)
for _p in (_V0_ROOT, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#El parser recorre las expresiones de forma recursiva, para evitar que un
#programa con anidamiento extremo rompa el proceso con un RecursionError,
#aumentamos el límite de Python y dejamos que el parser lo convierta en un diagnóstico controlado del tipo ExpressionTooDeepError
sys.setrecursionlimit(10_000)

from config import compilerconfig  # noqa: E402  (paquete config/ de la raiz)
from src.frontend.lexer import source_reader  # noqa: E402
from src.frontend.lexer.lexer import Lexer  # noqa: E402
from src.frontend.parser.parser import Parser  # noqa: E402

_PHASE_DEPS: set[str] = set()


def _load_config(source_path: Optional[str]) -> dict:
    """
    Configuración anclada al fuente: se busca el ``.suriaX_config.yaml``
    subiendo desde el directorio del ``.srcx`` (así compilar desde cualquier
    punto encuentra la MISMA config) NUNCA devuelve ``None``: en el peor caso
    genera la configuracion por defecto 
    """
    start = os.path.dirname(os.path.abspath(source_path)) if source_path else None
    try:
        return compilerconfig.reload_config(start_dir=start)
    except Exception:
        config = compilerconfig.default_config()
        config["_root"] = start or os.getcwd()
        return config


def _print_errors(title: str, errors) -> None:
    print(f"\n=== {title} ({len(errors)}) ===", file=sys.stderr)
    for err in errors:
        sev = getattr(err, "severity", "critical")
        print(f"  [{sev}] {err.code}: {err.message}  ({err.loc})", file=sys.stderr)


def _emit_library_units(libraries: dict, config: dict, log,
                        times: dict, *, hir_text: bool = False) -> Optional[str]:
    """
    Emite un ``<alias>.phir`` + ``<alias>.txt`` por unidad ``.libsrx`` cargada

    Recorre un *worklist*: si una librería importa otras, sus unidades se
    encolan también (cada ``Module`` referencia solo las suyas), Cada unidad
    corre su PROPIO pipeline completo (la carga del import solo llegó a la
    pasada 1)

    los ``.phir`` quedan junto al del módulo principal, así el
    module-linker del intérprete los resuelve por ruta relativa.

    Un PAQUETE llega como su carpeta: la unidad que se emite es su archivo
    padre (``main.libsrx``); sus submódulos vienen aparte, ya calificados
    (``IO.stdp``), porque la Semántica los registró al resolver el import.

    Devuelve un mensaje de error (str) si alguna unidad no pudo generarse
    """
    from src.frontend.semantic import analyze
    from src.frontend.parser.typed_ast import resolve_types
    from src.HIR.emmit_IR import build_module, module_to_text
    from src.linker_p.resolver import PACKAGE_PARENT, package_parent

    dumps_dir = compilerconfig.dumps_dir(config)
    pending = dict(libraries)
    done: set = set()
    failed: Optional[str] = None

    while pending:
        alias, lib_path = pending.popitem()
        if alias in done:
            continue
        done.add(alias)
        if os.path.isdir(lib_path):
            # un PAQUETE es una carpeta: la unidad ejecutable es su archivo
            # PADRE ('main.libsrx'), los submódulos NO se emiten desde aquí,cada uno llegó a 'libraries' como su propia unidad 
            parent = package_parent(lib_path, os.path.basename(lib_path))
            if parent is None:  # pragma: no cover - el linker ya lo exigio (linker_p/)
                failed = (f"el paquete '{alias}' no tiene archivo padre "
                          f"('{PACKAGE_PARENT}'); su .phir no se emitió")
                print(f"  {failed}", file=sys.stderr)
                continue
            lib_path = parent

        lib_source = source_reader.read_file(lib_path)
        lib_lexer = Lexer(lib_source, file=lib_path)
        lib_parser = Parser(lib_lexer.tokenize())
        lib_program = lib_parser.parse()
        resolve_types(lib_program)
        sub_libs: dict = {}
        lib_table, lib_errors = analyze(
            lib_program, source_path=lib_path, config=config,
            libraries=sub_libs,
        )
        for sub_alias, sub_path in sub_libs.items():
            if sub_alias not in done:
                pending[sub_alias] = sub_path

        if lib_lexer.errors or lib_parser.ctx.errors or lib_errors:
            failed = f"la unidad '{alias}' tiene errores; su .phir no se emitió"
            print(f"  {failed}", file=sys.stderr)
            continue

        module, hir_errors = build_module(
            lib_program, lib_table, source_file=lib_path, libraries=sub_libs,
        )
        if hir_errors:
            _print_errors(f"errores del HIR ({alias})", hir_errors)
            log.error_batch(hir_errors, source_file=lib_path)
            failed = f"la unidad '{alias}' no pudo emitirse"
            continue

        data = module.SerializeToString()
        text = module_to_text(module) if hir_text else None
        out = compilerconfig.dump_hir(
            data, source_path=lib_path, config=config,
            out_path=os.path.join(dumps_dir, f"{alias}.phir"), text=text,
        )
        print(f"  unidad '{alias}': {len(data)} bytes -> {out}"
              f"{' (+ .txt)' if text else ''}")

    return failed


def _emit_diagnostics(path: str) -> int:
    """
    Canal del LSP(Extension): corre el frontend (lexer -> parser -> AST-tipado
    -> Semantica, con resolucion real de .libsrx), emite en stdout un JSON con
    TODOS los diagnosticos y notas
    
    Silencioso (nada a disco/log), rapido (sin HIR ni ejecucion) y exit 0 aunque haya diagnosticos: el cliente los lee del
    JSON, no del exit code (distingue 'compilo con errores' de 'el proceso fallo')
    
    Ante un archivo inexistente devuelve un JSON con un diagnostico sintetico, no un traceback.
    """
    import json

    def _emit(payload: dict) -> int:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if not os.path.isfile(path):
        return _emit({"file": path, "diagnostics": [{
            "code": "IO000", "message": f"archivo no encontrado: {path}",
            "line": 1, "column": 1, "severity": "critical", "phase": "io"}]})

    from src.frontend.parser.typed_ast import resolve_types
    from src.frontend.semantic import analyze

    config = _load_config(path)
    diagnostics: list = []
    try:
        source = source_reader.read_file(path)
        lexer = Lexer(source, file=path)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse()
        resolve_types(program)
        notes: list = []
        _table, sem_errors = analyze(
            program, source_path=path, config=config, notes=notes, libraries={})

        for err in (*lexer.errors, *parser.ctx.errors, *sem_errors):
            #to_dict() ya trae la severidad real (critical / panic / ...)
            diagnostics.append(err.to_dict())
        # Fase HIR SIN construir el HIR (sin protobuf): si el AST es estructuralmente válido (parseó limpio), marca los constructos RBMM que el build
        # rechazaría con HIR005 — así el editor no se los 'salta' (ver emmit_IR.collect_unsupported). Los errores semánticos no impiden esta
        # detección: el AST sigue completo
        if not lexer.errors and not parser.ctx.errors:
            from src.HIR.emmit_IR import collect_unsupported
            for err in collect_unsupported(program):
                diagnostics.append(err.to_dict())
        for note in notes:
            diagnostics.append({
                "code": note.get("code"), "message": note.get("message"),
                "line": note.get("line"), "column": note.get("column"),
                "file": note.get("file"), "severity": "note",
                "phase": "linker"})
    except Exception as exc:  #NUNCA romper el canal del editor con un traceback
        diagnostics.append({
            "code": "ICE000", "message": f"error interno del compilador: {exc}",
            "line": 1, "column": 1, "severity": "panic", "phase": "internal"})

    return _emit({"file": path, "diagnostics": diagnostics})


def _run_source(path: str, *, emit_ast_json: Optional[str] = None,
                emit_tokens: Optional[str] = None,
                emit_hir: Optional[str] = None,
                run: bool = False, show_times: bool = False,
                debug: bool = False, hir_text: bool = False,
                trace_exec: bool = False, trace_memory: bool = False,
                dump_symbols: Optional[str] = None) -> int:
    if not os.path.isfile(path):
        print(f"archivo no encontrado: {path}", file=sys.stderr)
        return 2

    # cronometraje por fase: perf_counter alrededor de cada etapa (costo: una resta por fase). Se imprime solo con --time.
    times: dict[str, float] = {}
    t0 = time.perf_counter()
    # --debug implica recolectar todo lo que las fases ya producen (cero
    # computo extra, solo se retiene y se serializa al final).
    report = None
    trace_events: list = [] if debug else None
    if debug:
        show_times = True
        hir_text = True

    #configuracion + dependencias de la fase actual
    config = _load_config(path)
    # ¿el target pide ejecutar? ('interp' en el yaml, o --run que lo fuerza)
    target = ((config.get("compilation") or {}).get("target")
              or config.get("target") or "")
    run = run or target in ("interp", "interpreter")
    if run and emit_hir is None:
        emit_hir = ""  
    # ejecutar exige el .phir: se emite a ./dumps
    # el log se abre a nombre de este mismo, todo lo que produzca su compilacion -- incluidos los errores de las .libsrx que importe -- va a
    # 'log/<fuente>.log' y solo ahi
    log = compilerconfig.CompilerLog(config, source_path=path)
    # la fase HIR es la unica que exige protobuf
    #no imponer la dependencia la dependencia si no se emite el HIR, al menos que se use el interprete
    phase_deps = _PHASE_DEPS | ({"protobuf"} if emit_hir is not None else set())
    try:
        compilerconfig.ensure_dependencies(required=phase_deps)
    except compilerconfig.DependencyError as exc:
        print(exc, file=sys.stderr)
        return 3
    times["config+deps"] = time.perf_counter() - t0

    #decodificacion UTF-8 -> str
    t = time.perf_counter()
    source = source_reader.read_file(path)
    times["source_reader"] = time.perf_counter() - t

    #lexer -> list[Token]
    t = time.perf_counter()
    lexer = Lexer(source, file=path)
    tokens = lexer.tokenize()
    times["lexer"] = time.perf_counter() - t

    #volcado de tokens (independiente de que el resto del pipeline siga)
    if emit_tokens is not None:
        out = compilerconfig.dump_tokens_txt(
            tokens, source_path=path, config=config, out_path=emit_tokens or None,
        )
        print(f"tokens volcados en: {out}")

    #parser: ¿directiva '#test <fase>'? -> volcado de esa fase y fin
    #uso principal de la directiva `#test`? debug, fuera de eso 
    #la directiva no cuenta con otro proposito 
    parser = Parser(tokens)
    executed = parser.run_test_directive(source_path=path)

    exit_code = 0
    phir_path: Optional[str] = None
    if debug:
        report = compilerconfig.DebugReport(path, config)
        report.environment()
        report.dependencies(compilerconfig.check_dependencies())
        report.tokens(tokens)
    if executed is None:
        #pipeline completo disponible: AST -> AST-tipado -> Semantica
        from src.frontend.parser.typed_ast import resolve_types
        from src.frontend.semantic import analyze

        t = time.perf_counter()
        program = parser.parse()
        times["parser"] = time.perf_counter() - t

        t = time.perf_counter()
        resolve_types(program)
        times["ast-tipado"] = time.perf_counter() - t

        t = time.perf_counter()
        notes: list = []
        libraries: dict = {}
        table, sem_errors = analyze(
            program, source_path=path, config=config, notes=notes,
            libraries=libraries,
        )
        times["semantica"] = time.perf_counter() - t

        n_syms = len(table.global_scope.values) + len(table.global_scope.types)
        print(
            f"frontend OK: {len(tokens)} tokens, {len(program.items)} items, "
            f"{n_syms} simbolos globales, {len(table.hooks)} hooks, "
            f"{len(table.casts)} casts"
        )

        # NOTAS: consola (breve) + log estructurado
        # las notas no detienen compilacion, mas sin embargo tampoco deben ser ignoradas
        for note in notes:
            print(f"  NOTA {note['code']}: {note['message']}", file=sys.stderr)
            log.note(note["code"], note["message"], file=note.get("file"),
                     line=note.get("line"), column=note.get("column"))

        if parser.ctx.errors:
            _print_errors("errores de sintaxis", parser.ctx.errors)
            log.error_batch(parser.ctx.errors, source_file=path)
            exit_code = 1
        if sem_errors:
            _print_errors("errores semanticos", sem_errors)
            log.error_batch(sem_errors, source_file=path)
            exit_code = 1

        if report is not None:
            report.metrics(
                tokens=len(tokens), items=len(program.items),
                simbolos_globales=n_syms, hooks=len(table.hooks),
                casts=len(table.casts), librerias=len(libraries),
                errores_sintaxis=len(parser.ctx.errors),
                errores_semanticos=len(sem_errors),
            )
            report.ast(program).symbols(table)
            report.diagnostics("ERRORES DE SINTAXIS", parser.ctx.errors)
            report.diagnostics("ERRORES SEMANTICOS", sem_errors)

        #volcado opcional del AST-tipado (ya anotado) a JSON
        #NOTE: el wASM no deberia usar el JSON del AST normal al menos que
        #explicitamente se indique "--use-ntypeAST"(boton) en la version web
        #no requiere implementacion extra en el compilador
        if emit_ast_json is not None:
            out = compilerconfig.dump_ast_json(
                program, source_path=path, config=config,
                out_path=emit_ast_json or None,
            )
            print(f"AST-tipado volcado en: {out}")

        #volcado opcional de la tabla de simbolos como UML/Mermaid
        #
        if dump_symbols is not None:
            from include.symbols_uml import symbol_table_to_mermaid
            out_path = dump_symbols or os.path.join(
                compilerconfig.dumps_dir(config),
                os.path.basename(path) + ".symbols.mmd")
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(symbol_table_to_mermaid(table))
            print(f"tabla de simbolos (UML/Mermaid) volcada en: {out_path}")

        # fase HIR: solo con el pipeline LIMPIO (el puente NO SE CRUZA
        # CON UN PROGRAMA INVALIDO, los errores del emisor son HIRxxx)
        # Se escribe el binario .phir Y su vista de texto .phir.txt (facilita debug), junto a 
        # .phir POR unidad .libsrx importada (Module.libraries las referencia).
        if emit_hir is not None:
            if exit_code != 0 or lexer.errors:
                print("HIR no emitido: hay errores previos", file=sys.stderr)
            else:
                from src.HIR.emmit_IR import build_module, module_to_text  # diferido (protobuf)

                t = time.perf_counter()
                module, hir_errors = build_module(
                    program, table, source_file=path, libraries=libraries,
                )
                if hir_errors:
                    _print_errors("errores del HIR", hir_errors)
                    log.error_batch(hir_errors, source_file=path)
                    exit_code = 1
                else:
                    hir_bytes = module.SerializeToString()
                    # la vista de TEXTO del .phir solo se escribe si se pide
                    # (--hir-text o --debug): es el artefacto de debugging del
                    # formato, no parte de la compilacion normal.
                    text = module_to_text(module) if hir_text else None
                    phir_path = compilerconfig.dump_hir(
                        hir_bytes, source_path=path, config=config,
                        out_path=emit_hir or None, text=text,
                    )
                    print(f"HIR ({len(hir_bytes)} bytes) generado en: "
                          f"{phir_path}{' (+ .txt)' if text else ''}")
                    if report is not None:
                        report.hir_text(text)
                times["hir-emit"] = time.perf_counter() - t

                if libraries and exit_code == 0:
                    t = time.perf_counter()
                    failed = _emit_library_units(libraries, config, log, times,
                                                 hir_text=hir_text)
                    times["hir-libs"] = time.perf_counter() - t
                    if failed and run:
                        print(f"no se ejecuta: {failed}", file=sys.stderr)
                        run = False
                        exit_code = 1

    #reporte de errores lexicos recuperados
    if lexer.errors:
        _print_errors("errores lexicos", lexer.errors)
        log.error_batch(lexer.errors, source_file=path)
        exit_code = 1

    #un solo flush de logs por compilacion (cero I/O por evento)
    log_file = log.flush()
    if log_file:
        print(f"(diagnosticos registrados en {log_file})", file=sys.stderr)

    # target 'interp' / --run: entregar el .phir al interprete EN PROCESO
    # (sin subprocess ni reparseo) Con --debug la traza se ACUMULA en
    # 'trace_events' para el reporte en vez de imprimirse
    if run and exit_code == 0 and phir_path is not None:
        t = time.perf_counter()
        from runtime.interpreter import interpreter as interp
        from runtime.interpreter import loader as interp_loader

        icfg = dict(config.get("interpreter") or {})
        icfg.setdefault("entry", "main")
        if trace_memory:
            icfg["trace_memory"] = True
        if trace_exec:
            icfg["trace_exec"] = True
        try:
            image = interp_loader.load_image(phir_path)
            exit_code = interp.run(image, {"interpreter": icfg},
                                   events=trace_events)
        except interp_loader.HIRLoadError as exc:
            print(f"error cargando HIR: {exc}", file=sys.stderr)
            exit_code = 3
        times["interprete"] = time.perf_counter() - t

    if show_times:
        total = sum(times.values())
        print("\n=== tiempos por fase ===", file=sys.stderr)
        for name, secs in times.items():
            print(f"  {name:<14} {secs * 1000:8.2f} ms", file=sys.stderr)
        print(f"  {'TOTAL':<14} {total * 1000:8.2f} ms", file=sys.stderr)

    #reporte general de depuracion (una sola escritura al final)
    if report is not None:
        report.diagnostics("ERRORES LEXICOS", lexer.errors)
        report.trace(trace_events)
        report.timings(times)
        out = report.write()
        print(f"reporte de depuracion en: {out}", file=sys.stderr)

    return exit_code


def main(argv: list[str]) -> int:
    """
    FLAGS
    TODO: a futuro esto NO DEBERIA DE ESTAR AQUI, el encargado es
    suriniX, mientras no se encuentre una version funcional se alojara en el compilador
    
    """
    parser = argparse.ArgumentParser(
        prog="suriaX",
        description="Compilador suriaX (Pre-Alpha)",
    )
    parser.add_argument("source", nargs="?", help="archivo .srcx a procesar")
    parser.add_argument(
        "--check", action="store_true",
        help="verifica las dependencias del compilador",
    )
    parser.add_argument(
        "--init-config", action="store_true",
        help="genera un .suriaX_config.yaml por defecto",
    )
    parser.add_argument(
        "--emit-ast-json", nargs="?", const="", default=None, metavar="ARCHIVO",
        help="vuelca el AST-tipado a JSON"
             "ARCHIVO va a <dumps_dir>/<fuente>.ast.json",
    )
    parser.add_argument(
        "--emit-tokens", nargs="?", const="", default=None, metavar="ARCHIVO",
        help="vuelca el arreglo de tokens a texto sin ARCHIVO va a "
             "<dumps_dir>/<fuente>.tokens.txt",
    )
    parser.add_argument(
        "--emit-hir", nargs="?", const="", default=None, metavar="ARCHIVO",
        help="serializa el HIR tras una compilacion limpia sin "
             "ARCHIVO va a <dumps_dir>/<fuente>.phir + .phir.txt (requiere protobuf)",
    )
    parser.add_argument(
        "--dump-symbols-table", nargs="?", const="", default=None, metavar="ARCHIVO",
        dest="dump_symbols",
        help="vuelca la tabla de simbolos como diagrama de clases UML (Mermaid'classDiagram') "
             "sin ARCHIVO va a <dumps_dir>/<fuente>.symbols.mmd. ",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="fuerza el target 'interp': emite el HIR y lo ejecuta con el "
             "'target: interp' en .suriaX_config.yaml",
    )
    parser.add_argument(
        "--time", action="store_true", dest="show_times",
        help="tiempo de compilacion de cada fase(ms)",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="reporte GENERAL de depuracion en <dumps_dir>/<fuente>.debug.txt "
             "entorno, dependencias, metricas, tokens, AST, simbolos, HIR en "
             "texto, traza de ejecucion y tiempos",
    )
    parser.add_argument(
        "--hir-text", action="store_true", dest="hir_text",
        help="escribe la vista de TEXTO del HIR (<fuente>.phir.txt)",
    )
    parser.add_argument(
        "--trace-exec", action="store_true", dest="trace_exec",
        help="traza la ejecucion (llamadas/retornos anidados) al correr",
    )
    parser.add_argument(
        "--trace-memory", action="store_true", dest="trace_memory",
        help="traza las instrucciones de memoria (&, move, free) al correr",
    )
    parser.add_argument(
        "--emit-lang-info", action="store_true", dest="emit_lang_info",
        help="imprime en stdout la ESPECIFICACION del lenguaje en JSON "
             "(keywords por categoria, tokens, directivas, hooks, codigos de "
             "error) y termina. Fuente para el LSP/extension (no reimplementar "
             "el vocabulario a mano). No necesita un archivo fuente.",
    )
    parser.add_argument(
        "--emit-diagnostics", action="store_true", dest="emit_diagnostics",
        help="corre el frontend sobre el archivo y emite en stdout un JSON con "
             "TODOS los diagnosticos (codigo/mensaje/linea/columna/fase) y "
             "notas, Canal en vivo para el LSP. exit 0 aunque haya diagnosticos.",
    )
    args = parser.parse_args(argv[1:])

    if args.emit_lang_info:
        import json
        from include.lang_info import build_language_info
        print(json.dumps(build_language_info(), ensure_ascii=False, indent=2))
        return 0

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

    if args.emit_diagnostics:
        return _emit_diagnostics(args.source)

    return _run_source(args.source, emit_ast_json=args.emit_ast_json,
                       emit_tokens=args.emit_tokens, emit_hir=args.emit_hir,
                       run=args.run, show_times=args.show_times,
                       debug=args.debug, hir_text=args.hir_text,
                       trace_exec=args.trace_exec,
                       trace_memory=args.trace_memory,
                       dump_symbols=args.dump_symbols)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
