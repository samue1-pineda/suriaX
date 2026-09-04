"""El pipeline de compilación, sin terminal.

Es el antiguo ``V0/main.py::_run_source``, que hacía cinco cosas a la vez:
cargar la configuración, compilar, escribir artefactos, imprimir el progreso,
ejecutar el programa y decidir el código de salida. Todo junto significaba
que la única manera de compilar era pasando por el ``argparse``, y que
``suri run`` (suriniX) habría tenido que reimplementarlo o invocar al
proceso.

Aquí queda **solo compilar**. Lo que se contaba por ``print`` sale ahora por
el :class:`~driver.reporting.Reporter` que pase el llamador, lo que se
devolvía como un ``int`` es un :class:`~driver.options.CompileResult`, y
EJECUTAR es de :mod:`driver.execute`: el pipeline deja el ``.phir`` y dice si
el target lo pide, pero no lo lanza.
"""

from __future__ import annotations

import os
import time
from typing import Optional

import htims
from config import compilerconfig
from include import ast_nodes as ast
from src.frontend.lexer import source_reader
from src.frontend.lexer.lexer import Lexer
from src.frontend.parser.parser import Parser

from .options import (EXIT_COMPILE_ERROR, EXIT_CONFIG_ERROR,
                      EXIT_EXTENSION_ERROR, EXIT_FILE_NOT_FOUND,
                      EXIT_MISSING_DEPENDENCY, EXIT_OK, CompileOptions,
                      CompileResult)
from .reporting import Reporter, SilentReporter
from error_handler.error import blocks

#: dependencias que TODA compilación necesita (ninguna: el frontend completo
#: corre con la librería estándar, y la fase HIR tampoco: desde que el
#: '.phir' se escribe a mano, el compilador entero no necesita nada
#: instalado. Ver 'src/HIR/PROTOBUF_BRIDGE.md' secc. 2.
_PHASE_DEPS: set[str] = set()


def load_config(source_path: Optional[str]) -> dict:
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


def build_library_units(libraries: dict, config: dict, *,
                        hir_text: bool = False,
                        reporter: Optional[Reporter] = None,
                        log=None) -> tuple:
    """Compila cada unidad ``.libsrx`` cargada y devuelve SUS BYTES.

    Recorre un *worklist*: si una librería importa otras, sus unidades se
    encolan también (cada ``Module`` referencia solo las suyas). Cada unidad
    corre su PROPIO pipeline completo (la carga del import solo llegó a la
    pasada 1).

    Un PAQUETE llega como su carpeta: la unidad que se compila es su archivo
    padre (``main.libsrx``); sus submódulos vienen aparte, ya calificados
    (``IO.stdp``), porque la Semántica los registró al resolver el import.

    Construir y ESCRIBIR están separados a propósito: el mismo recorrido lo
    necesitan quien vuelca los ``.phir`` a disco (:func:`emit_library_units`)
    y quien solo quiere los bytes para dárselos a otro proceso — el
    playground los pone junto al módulo principal en un temporal. Duplicar el
    worklist para eso habría sido mantener dos veces la misma pregunta.

    Devuelve ``({alias: (bytes, texto|None, ruta)}, error|None)``.
    """
    from src.frontend.semantic import analyze
    from src.frontend.parser.typed_ast import resolve_types
    from src.HIR.emmit_IR import build_module, module_to_text, serialize
    from src.linker_p.resolver import PACKAGE_PARENT, package_parent

    reporter = reporter or SilentReporter()
    pending = dict(libraries)
    done: set = set()
    failed: Optional[str] = None
    unidades: dict = {}

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
                reporter.warn(f"  {failed}")
                continue
            lib_path = parent

        lib_source = source_reader.read_file(lib_path)
        lib_lexer = Lexer(lib_source, file=lib_path)
        lib_parser = Parser(lib_lexer.tokenize())
        lib_program = lib_parser.parse()
        resolve_types(lib_program)
        sub_libs: dict = {}
        # El alias del '#export' (la ÚLTIMA declaración del archivo, igual
        # que lo lee el linker). Hace falta aquí porque esta pasada vuelve a
        # analizar la librería por su cuenta para emitir su .phir: sin él sus
        # tipos saldrían sin calificar y no coincidirían con los que ya
        # registró el consumidor.
        export = lib_program.items[-1] if lib_program.items else None
        unidad = export.alias if isinstance(export, ast.ExportDirective) else ""
        lib_table, lib_errors = analyze(
            lib_program, source_path=lib_path, config=config,
            libraries=sub_libs, unit=unidad,
        )
        for sub_alias, sub_path in sub_libs.items():
            if sub_alias not in done:
                pending[sub_alias] = sub_path

        if lib_lexer.errors or lib_parser.ctx.errors or lib_errors:
            failed = f"la unidad '{alias}' tiene errores; su .phir no se emitió"
            reporter.warn(f"  {failed}")
            continue

        module, hir_errors = build_module(
            lib_program, lib_table, source_file=lib_path, libraries=sub_libs,
        )
        if hir_errors:
            reporter.diagnostics(f"errores del HIR ({alias})", hir_errors)
            if log is not None:
                log.error_batch(hir_errors, source_file=lib_path)
            failed = f"la unidad '{alias}' no pudo emitirse"
            continue

        unidades[alias] = (serialize(module),
                           module_to_text(module) if hir_text else None,
                           lib_path)

    return unidades, failed


def emit_library_units(libraries: dict, config: dict, log,
                       times: dict, *, hir_text: bool = False,
                       reporter: Optional[Reporter] = None) -> Optional[str]:
    """Escribe un ``<alias>.phir`` (+ ``.txt``) por unidad ``.libsrx`` cargada.

    Los ``.phir`` quedan junto al del módulo principal, así el module-linker
    del consumidor los resuelve por ruta relativa. Quien decide QUÉ unidades
    hay y las compila es :func:`build_library_units`; esto solo las vuelca.

    Devuelve un mensaje de error (str) si alguna unidad no pudo generarse.
    """
    reporter = reporter or SilentReporter()
    dumps_dir = compilerconfig.dumps_dir(config)
    unidades, failed = build_library_units(
        libraries, config, hir_text=hir_text, reporter=reporter, log=log)
    for alias, (data, text, lib_path) in unidades.items():
        out = compilerconfig.dump_hir(
            data, source_path=lib_path, config=config,
            out_path=os.path.join(dumps_dir, f"{alias}.phir"), text=text,
        )
        reporter.info(f"  unidad '{alias}': {len(data)} bytes -> {out}"
                      f"{' (+ .txt)' if text else ''}")
    return failed


def _titulo(fase: str, diagnosticos) -> str:
    """Encabezado del bloque de diagnosticos de una fase.

    Llamar "errores" a una lista que solo trae avisos es mentir en la unica
    linea que el usuario lee entera.
    """
    return f"{'errores' if blocks(diagnosticos) else 'avisos'} {fase}"


def compile_source(path: str, options: Optional[CompileOptions] = None, *,
                   reporter: Optional[Reporter] = None) -> CompileResult:
    """Compila ``path`` y devuelve lo que salió, sin imprimir nada por su cuenta.

    Es el cuerpo del antiguo ``V0/main.py::_run_source``, con dos cambios de
    fondo: lo que se contaba por ``print`` ahora va por el ``reporter`` (la
    CLI pone el suyo; un build system pondrá otro) y lo que se devolvía como
    un ``int`` ahora es un :class:`CompileResult` con todo lo que la
    compilación llegó a saber.

    NO ejecuta el programa aunque el target lo pida: deja ``should_run`` y el
    ``.phir`` listos y es el llamador quien decide (ver :mod:`driver.execute`).
    """
    options = options or CompileOptions()
    reporter = reporter or SilentReporter()
    emit_ast_json = options.emit_ast_json
    emit_tokens = options.emit_tokens
    emit_hir = options.emit_hir
    hir_pretty = options.hir_pretty
    dump_symbols = options.dump_symbols
    hir_text = options.hir_text
    run = options.run
    debug = options.debug

    result = CompileResult(path=path)
    if not os.path.isfile(path):
        result.status = EXIT_FILE_NOT_FOUND
        return result

    # Cronometraje por fase: un 'perf_counter' alrededor de cada etapa, o sea
    # una resta por fase. Se mide SIEMPRE y viaja en el resultado; quien lo
    # muestre (y si lo muestra) es cosa del llamador.
    times: dict[str, float] = {}
    t0 = time.perf_counter()
    # --debug implica recolectar todo lo que las fases ya producen (cero
    # computo extra, solo se retiene y se serializa al final).
    report = None
    trace_events: list = [] if debug else None
    if debug:
        # la vista LEGIBLE, no el volcado crudo del protobuf: para depurar un
        # programa se quiere ver el programa. '--hir-text' sigue disponible
        # para depurar el formato, que es otra pregunta.
        if hir_pretty is None:
            hir_pretty = ""

    #configuracion + dependencias de la fase actual
    config = load_config(path)
    result.config = config
    # Una configuracion mal escrita se descartaba en SILENCIO y el sintoma
    # aparecia lejos ("no se encontro la libreria X"). Ahora corta aqui: el
    # resto del pipeline resuelve rutas contra ella, asi que seguir seria
    # compilar contra unos ajustes que el usuario no escribio.
    config_errors = compilerconfig.errors_of(config)
    if config_errors:
        reporter.diagnostics("diagnosticos de configuracion", config_errors)
        result.diagnostics.extend(config_errors)
    # solo lo CRITICO corta: el resto del pipeline resuelve rutas contra la
    # configuracion, asi que seguir con unos ajustes ya rechazados seria
    # compilar contra algo que el usuario no escribio. Una advertencia (falta
    # 'pyyaml') si deja seguir: el frontend corre con la libreria estandar.
    if any(getattr(e, "severity", "critical") == "critical" for e in config_errors):
        result.status = EXIT_CONFIG_ERROR
        return result

    # capa HTIMS: ANTES del lexico. Descubre y valida las extensiones del
    # proyecto ('extends.srcx' + la lista 'extensions:' del yaml) y deja el
    # resultado en la config. Sin extensiones cuesta un stat y no dice nada;
    # con un manifiesto roto se aborta aqui, antes de tokenizar una linea:
    # el vocabulario del lenguaje depende de esto, asi que compilar contra un
    # conjunto de extensiones a medias reportaria errores en el .srcx que en
    # realidad son del manifiesto.
    t = time.perf_counter()
    _extensions, ext_errors = htims.discover(config)
    times["htims"] = time.perf_counter() - t

    # ¿el target pide ejecutar? ('interp' en el yaml, o --run que lo fuerza)
    target = ((config.get("compilation") or {}).get("target")
              or config.get("target") or "")
    run = run or target in ("interp", "interpreter")
    if run and emit_hir is None:
        emit_hir = ""
    # la vista legible se construye desde el MISMO Module que el .phir
    if hir_pretty is not None and emit_hir is None:
        emit_hir = ""  
    # ejecutar exige el .phir: se emite a ./dumps
    # el log se abre a nombre de este mismo, todo lo que produzca su compilacion -- incluidos los errores de las .libsrx que importe -- va a
    # 'log/<fuente>.log' y solo ahi
    log = compilerconfig.CompilerLog(config, source_path=path)
    if ext_errors:
        reporter.diagnostics("errores de extensiones", ext_errors)
        log.error_batch(ext_errors, source_file=path)
        result.diagnostics.extend(ext_errors)
        result.log_file = log.flush()
        result.status = EXIT_EXTENSION_ERROR
        return result
    # NINGUNA fase exige ya protobuf: el HIR se serializa a mano contra el
    # propio 'hir.proto' (ver 'src/HIR/stubs.py'). Antes esto anadia
    # 'protobuf' al emitir el HIR, y como emitirlo es parte de compilar, la
    # dependencia era de hecho obligatoria para todo.
    phase_deps = _PHASE_DEPS
    try:
        compilerconfig.ensure_dependencies(required=phase_deps)
    except compilerconfig.DependencyError as exc:
        reporter.warn(str(exc))
        result.status = EXIT_MISSING_DEPENDENCY
        return result
    # el descubrimiento de extensiones cae dentro de este tramo pero se
    # cronometra aparte: sumarlo dos veces inflaria el TOTAL.
    times["config+deps"] = time.perf_counter() - t0 - times["htims"]

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
        result.artifacts["tokens"] = out
        reporter.info(f"tokens volcados en: {out}")

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
        result.metrics = {
            "tokens": len(tokens), "items": len(program.items),
            "simbolos_globales": n_syms, "hooks": len(table.hooks),
            "casts": len(table.casts), "librerias": len(libraries),
        }
        reporter.info(
            f"frontend OK: {len(tokens)} tokens, {len(program.items)} items, "
            f"{n_syms} simbolos globales, {len(table.hooks)} hooks, "
            f"{len(table.casts)} casts"
        )

        # NOTAS: consola (breve) + log estructurado
        # las notas no detienen compilacion, mas sin embargo tampoco deben ser ignoradas
        result.notes.extend(notes)
        for note in notes:
            reporter.warn(f"  NOTA {note['code']}: {note['message']}")
            log.note(note["code"], note["message"], file=note.get("file"),
                     line=note.get("line"), column=note.get("column"))

        # Lo que DETIENE la compilacion es la severidad, no el hecho de haber
        # diagnosticos: un aviso se reporta y la compilacion continua, que es
        # lo que la escala de 'Severity' prometia desde el principio.
        if parser.ctx.errors:
            reporter.diagnostics(_titulo("sintaxis", parser.ctx.errors),
                                 parser.ctx.errors)
            log.error_batch(parser.ctx.errors, source_file=path)
            result.diagnostics.extend(parser.ctx.errors)
            if blocks(parser.ctx.errors):
                exit_code = EXIT_COMPILE_ERROR
        if sem_errors:
            reporter.diagnostics(_titulo("semanticos", sem_errors), sem_errors)
            log.error_batch(sem_errors, source_file=path)
            result.diagnostics.extend(sem_errors)
            if blocks(sem_errors):
                exit_code = EXIT_COMPILE_ERROR

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
            result.artifacts["ast"] = out
            reporter.info(f"AST-tipado volcado en: {out}")

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
            result.artifacts["symbols"] = out_path
            reporter.info(f"tabla de simbolos (UML/Mermaid) volcada en: {out_path}")

        # fase HIR: solo con el pipeline LIMPIO (el puente NO SE CRUZA
        # CON UN PROGRAMA INVALIDO, los errores del emisor son HIRxxx)
        # Se escribe el binario .phir Y su vista de texto .phir.txt (facilita debug), junto a 
        # .phir POR unidad .libsrx importada (Module.libraries las referencia).
        if emit_hir is not None:
            if exit_code != 0 or lexer.errors:
                reporter.warn("HIR no emitido: hay errores previos")
            else:
                from src.HIR.emmit_IR import (build_module,  # diferido (protobuf)
                                              module_to_text, serialize)

                # el descriptor pool de protobuf se construye una vez por
                # PROCESO y cuesta decenas de ms. Se carga aqui, con su propia
                # medida, en vez de dentro de 'build_module': si no, el coste
                # fijo de la dependencia se cobraba a la emision y hacia
                # parecer que emitir un programa de 50 tokens tardaba 30 ms.
                t = time.perf_counter()
                from src.HIR.stubs import load_hir_pb2
                load_hir_pb2()
                times["hir-protobuf"] = time.perf_counter() - t

                t = time.perf_counter()
                module, hir_errors = build_module(
                    program, table, source_file=path, libraries=libraries,
                )
                if hir_errors:
                    reporter.diagnostics("errores del HIR", hir_errors)
                    log.error_batch(hir_errors, source_file=path)
                    result.diagnostics.extend(hir_errors)
                    exit_code = EXIT_COMPILE_ERROR
                else:
                    hir_bytes = serialize(module)
                    # la vista de TEXTO del .phir solo se escribe si se pide
                    # (--hir-text o --debug): es el artefacto de debugging del
                    # formato, no parte de la compilacion normal.
                    text = module_to_text(module) if hir_text else None
                    phir_path = compilerconfig.dump_hir(
                        hir_bytes, source_path=path, config=config,
                        out_path=emit_hir or None, text=text,
                    )
                    result.artifacts["hir"] = phir_path
                    reporter.info(f"HIR ({len(hir_bytes)} bytes) generado en: "
                                  f"{phir_path}{' (+ .txt)' if text else ''}")
                    if report is not None:
                        report.hir_text(text)

                    # vista LEGIBLE, en streaming: para un programa grande son
                    # megabytes que no tiene sentido armar en memoria (era
                    # justo el defecto de la vista de texto del protobuf).
                    if hir_pretty is not None:
                        from src.HIR.pretty import write_pretty
                        pretty_path = compilerconfig.hir_pretty_path(
                            source_path=path, config=config,
                            out_path=hir_pretty or None)
                        with open(pretty_path, "w", encoding="utf-8") as fh:
                            write_pretty(module, fh)
                        result.artifacts["hir_pretty"] = pretty_path
                        reporter.info(f"HIR legible en: {pretty_path}")
                times["hir-emit"] = time.perf_counter() - t

                if libraries and exit_code == 0:
                    t = time.perf_counter()
                    failed = emit_library_units(libraries, config, log, times,
                                                hir_text=hir_text,
                                                reporter=reporter)
                    times["hir-libs"] = time.perf_counter() - t
                    if failed and run:
                        reporter.warn(f"no se ejecuta: {failed}")
                        run = False
                        exit_code = EXIT_COMPILE_ERROR

    #reporte de errores lexicos recuperados
    if lexer.errors:
        reporter.diagnostics("errores lexicos", lexer.errors)
        log.error_batch(lexer.errors, source_file=path)
        result.diagnostics.extend(lexer.errors)
        exit_code = EXIT_COMPILE_ERROR

    #un solo flush de logs por compilacion (cero I/O por evento)
    result.log_file = log.flush()

    result.status = exit_code
    result.phir_path = phir_path if exit_code == EXIT_OK else None
    result.should_run = bool(run) and exit_code == EXIT_OK and phir_path is not None
    result.times = times
    result.trace_events = trace_events
    # el reporte de depuracion se cierra en 'finish_debug_report': necesita la
    # traza, que solo existe DESPUES de ejecutar. Se guarda el objeto a medias.
    result.debug_report = report
    result.lexer_errors = lexer.errors
    return result


__all__ = ["load_config", "compile_source", "emit_library_units"]
