"""Canales de CONSULTA: lo que un editor o un visualizador le pregunta al
compilador sin pedirle que compile un artefacto.

Son tres preguntas distintas y ninguna produce un ``.phir``:

- ``emit_stage``        — enséñame UNA fase de este archivo (lo que hace
  ``#test <fase>``, pero pedido desde fuera, para que el visualizador no
  obligue al usuario a escribir una directiva);
- ``emit_diagnostics``  — dime TODO lo que está mal en este buffer, en JSON;
- ``emit_extensions``   — dime qué extensiones (HTIMS) tiene este proyecto.

Viven en el driver y no en la CLI porque la pregunta es del compilador; la
CLI solo elige que la respuesta salga por stdout. ``emit_diagnostics`` y
``emit_extensions`` devuelven el dato y quien llama lo serializa; ``emit_stage``
escribe por el volcador del parser, que ya es un contrato aparte.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

import htims
from error_handler.InternalCompilerError import InternalCompilerError
from error_handler.lex_error import InvalidUnicodeCharacterError
from src.frontend.lexer import source_reader
from src.frontend.lexer.lexer import Lexer
from src.frontend.parser.parser import Parser

from .options import (EXIT_EXTENSION_ERROR, EXIT_FILE_NOT_FOUND,
                      EXIT_INTERNAL_ERROR, EXIT_OK)
from .pipeline import load_config


def emit_extensions(source_path: Optional[str]) -> tuple[dict, int]:
    """Vuelca a stdout, en JSON, lo que la capa HTIMS descubrio del proyecto.

    Es la ventana a una fase que de otro modo es invisible: que hooks declara
    el usuario, en que archivo, con que firma, y que lineas puede copiar a su
    '.suriaX_config.yaml'. Sin extensiones emite un objeto vacio, no un error
    -- no tenerlas es lo normal.

    exit 0 siempre que la consulta se pueda responder; 4 si el manifiesto o
    alguna declaracion tienen errores (mismo codigo que la compilacion).
    """
    config = load_config(source_path)
    extensions, errors = htims.discover(config)
    payload = {
        "root": config.get("_root"),
        "project": config.get("project") or "",
        "extensions": extensions.to_dict() if extensions is not None else None,
        "config_entries": config.get("extensions") or [],
        "diagnostics": [err.to_dict() for err in errors],
    }
    return payload, (EXIT_EXTENSION_ERROR if errors else EXIT_OK)


def emit_stage(path: str, stage: str, *,
               from_stdin: bool = False) -> tuple[int, Optional[str]]:
    """Vuelca UNA fase del pipeline a stdout.

    Es lo mismo que ``#test <fase>`` pero pedido desde fuera, para que un
    visualizador pueda mostrar cualquier etapa de un archivo sin obligar al
    usuario a escribir una directiva en el. Acepta ``--stdin``, asi que tambien
    funciona sobre un buffer sin guardar.

    Devuelve 2 si la fase no existe (con la lista en stderr), 6 si el
    compilador falló (ICE000, con su traza en stderr) y 0 en cualquier otro
    caso: el contenido se lee de stdout, no del exit code.
    """
    from src.linker_p import nueva_compilacion
    nueva_compilacion()     # la caché del linker es de ESTE volcado
    available = Parser.available_stages()
    if stage.lower() not in available:
        return (EXIT_FILE_NOT_FOUND,
                f"fase desconocida: '{stage}'\n"
                f"  disponibles: {', '.join(available)}")

    if not from_stdin and not os.path.isfile(path):
        return EXIT_FILE_NOT_FOUND, f"archivo no encontrado: {path}"

    try:
        if from_stdin:
            source = source_reader.decode(sys.stdin.buffer.read(), file=path)
        else:
            source = source_reader.read_file(path)
        lexer = Lexer(source, file=path)
        parser = Parser(lexer.tokenize())
        parser.fuente = source   # la vista de desugaring cita las lineas
        # Una directiva '#test' en el propio archivo se consume: la fase que se
        # muestra es la que pidio el visualizador, no la que traiga el fuente.
        parser.consume_test_directive()
        parser.run_stage(stage, source_path=path)
        if lexer.errors:
            detalle = "\n".join(
                f"  {err.code}: {err.message}  ({err.loc})" for err in lexer.errors)
            return EXIT_OK, f"\n=== errores lexicos ({len(lexer.errors)}) ===\n{detalle}"
    except InvalidUnicodeCharacterError as err:
        # un fuente que no es UTF-8 es un error del programa (LEX008), no un
        # fallo del compilador
        return EXIT_OK, (f"\n=== errores lexicos (1) ===\n"
                         f"  {err.code}: {err.message}  ({err.loc})")
    except Exception as exc:  # noqa: BLE001 - nunca romper el visor con un traceback
        # Antes esto devolvía EXIT_OK con "no se pudo volcar la fase": un
        # fallo del compilador que salía como éxito y sin decir qué falló.
        # Ahora es un ICE: su mensaje nombra la excepción y el sitio del
        # compilador, y el código de salida dice que algo se rompió.
        ice = InternalCompilerError.desde(exc, phase=f"volcado de la fase '{stage}'",
                                          file=path)
        return EXIT_INTERNAL_ERROR, ice.render()
    return EXIT_OK, None


def _token_extents(tokens) -> dict:
    """Indice ``(linea, columna) -> (linea_fin, columna_fin)`` de cada token.

    Un diagnostico se levanta con la posicion de INICIO de un token, y el token
    conoce su lexema: de ahi sale el final sin que ningun sitio de ``raise`` tenga
    que cambiar. Es la unica forma barata de dar un RANGO, que es lo que un editor
    necesita para subrayar; con solo el inicio, un consumidor no puede saber
    cuanto marcar y termina subrayando un caracter o inventandose el tramo.

    Un lexema multilinea (una cadena con saltos, un ``RAW_BLOCK``) se cuenta como
    lo que es, no como si acabara en su propia linea.
    """
    extents: dict = {}
    for tok in tokens:
        lexeme = tok.lexeme or ""
        if "\n" in lexeme:
            saltos = lexeme.count("\n")
            end = (tok.ln + saltos, len(lexeme.rsplit("\n", 1)[1]) + 1)
        else:
            end = (tok.ln, tok.col + max(len(lexeme), 1))
        # El primer token de una posicion manda: los siguientes no existen (dos
        # tokens no empiezan en el mismo sitio), pero un lexer con recuperacion
        # podria emitir uno sintetico encima.
        extents.setdefault((tok.ln, tok.col), end)
    return extents


def _with_extent(entry: dict, extents: dict) -> dict:
    """Anota ``end_line``/``end_column`` a partir del token que empieza ahi.

    Si el diagnostico no cae sobre el inicio de un token -- posible cuando lo
    levanta una fase que ya no habla de tokens -- el rango degrada a un solo
    caracter, que es exactamente lo que se sabe.
    """
    start = (entry.get("line"), entry.get("column"))
    end_line, end_column = extents.get(start, (start[0], (start[1] or 1) + 1))
    entry["end_line"] = end_line
    entry["end_column"] = end_column
    return entry


def _with_file(entry: dict, path: str) -> dict:
    """Rellena ``file`` cuando el error no lo trae.

    Solo el lexer recibe la ruta al construirse; parser y semantica levantan sus
    errores con linea/columna y nada mas, asi que el canal salia con
    ``"file": null`` en la mayoria de los diagnosticos. El canal SI conoce la
    ruta, y un consumidor que agrupe por archivo la necesita.
    """
    if entry.get("file") is None:
        entry["file"] = path
    return entry


def emit_index(path: str, *, from_stdin: bool = False,
               source: Optional[str] = None) -> dict:
    """Canal del LSP para hover, ir a la definicion y completar: los
    diagnosticos (lo mismo que ``--emit-diagnostics``) MAS el indice del
    archivo —sus simbolos con tipo, firma, posicion y comentario, donde se usa
    cada uno y que va despues de un ``.``— en UNA sola pasada del frontend
    (ver ``src/frontend/semantic/index.py``). Sin indice si el parseo no fue
    limpio: un arbol recuperado en modo panico no es de fiar.

    Construir el indice tambien puede fallar, y el canal tiene la misma regla
    que el de diagnosticos: nunca un traceback. Un fallo aqui sale como
    ``ICE000`` entre los diagnosticos, con el indice vacio; antes escapaba
    como excepcion (el primer consumidor en atraparlo fue el LSP)."""
    from src.frontend.semantic.index import INDEX_VERSION
    vacio = {"index_version": INDEX_VERSION, "symbols": [],
             "references": [], "members": {}}
    estado: dict = {}
    payload = emit_diagnostics(path, from_stdin=from_stdin, source=source,
                               _estado=estado)
    if "table" not in estado:
        payload.update(vacio)
        return payload
    try:
        from src.frontend.semantic.index import build_index
        payload.update(build_index(estado["program"], estado["table"], path=path,
                                   source=estado["source"],
                                   libraries=estado["libraries"]))
    except Exception as exc:  # noqa: BLE001 - el canal nunca lanza
        ice = InternalCompilerError.desde(exc, phase="indice del editor",
                                          file=path)
        payload["diagnostics"].append({
            "code": "ICE000", "message": ice.message, "line": 1, "column": 1,
            "end_line": 1, "end_column": 2, "severity": "panic",
            "phase": "index", "file": path})
        payload.update(vacio)
    return payload


def emit_diagnostics(path: str, *, from_stdin: bool = False,
                     source: Optional[str] = None,
                     _estado: Optional[dict] = None) -> dict:
    """
    Canal del LSP(Extension): corre el frontend (lexer -> parser -> AST-tipado
    -> Semantica, con resolucion real de .libsrx), emite en stdout un JSON con
    TODOS los diagnosticos y notas
    
    Silencioso (nada a disco/log), rapido (sin HIR ni ejecucion) y exit 0 aunque haya diagnosticos: el cliente los lee del
    JSON, no del exit code (distingue 'compilo con errores' de 'el proceso fallo')
    
    Ante un archivo inexistente devuelve un diagnostico sintetico, no un traceback.

    ``source``: el TEXTO a analizar, para quien lo tiene en memoria (un
    servidor de lenguaje con el buffer del editor). Es lo mismo que
    ``from_stdin`` sin pasar por la entrada estandar, que en un servidor es
    el canal del protocolo. ``path`` sigue anclando las librerias.
    """
    hay_texto = from_stdin or source is not None
    from src.linker_p import nueva_compilacion
    nueva_compilacion()     # la caché del linker es de ESTE análisis

    def _emit(payload: dict) -> dict:
        # Devuelve el DATO, no lo imprime: quien decide que esto salga por
        # stdout es la CLI. Un LSP embebido consume el dict directamente.
        return payload

    # Con --stdin el archivo puede no existir todavia (un buffer sin guardar):
    # la ruta se usa para anclar la resolucion de .libsrx, no para leer.
    if not hay_texto and not os.path.isfile(path):
        return _emit({"file": path, "diagnostics": [{
            "code": "IO000", "message": f"archivo no encontrado: {path}",
            "line": 1, "column": 1, "severity": "critical", "phase": "io"}]})

    from src.frontend.parser.typed_ast import resolve_types
    from src.frontend.semantic import analyze

    config = load_config(path)
    diagnostics: list = []

    # capa HTIMS: sus errores son del PROYECTO (manifiesto o declaraciones),
    # no del buffer abierto, pero el editor tiene que verlos -- van con su
    # propia ruta en 'file'. A diferencia de la compilacion, aqui NO se aborta:
    # dejar el archivo sin analizar por un manifiesto roto seria apagarle los
    # diagnosticos al usuario justo cuando esta arreglando algo.
    _extensions, ext_errors = htims.discover(config)
    for err in ext_errors:
        # el rango degrada a un caracter: un manifiesto no tiene tokens, asi
        # que no hay extension que consultar (misma regla que '_with_extent'
        # cuando el diagnostico no cae sobre el inicio de un token).
        entry = _with_file(err.to_dict(), path)
        entry["end_line"] = entry["line"]
        entry["end_column"] = (entry["column"] or 1) + 1
        diagnostics.append(entry)

    try:
        # Mismo decodificado y normalizado de saltos de linea en ambos casos:
        # un buffer analizado por stdin tiene que dar exactamente los mismos
        # diagnosticos que el mismo texto guardado en disco.
        if source is not None:
            source = source_reader.decode(source.encode("utf-8"), file=path)
        elif from_stdin:
            source = source_reader.decode(sys.stdin.buffer.read(), file=path)
        else:
            source = source_reader.read_file(path)
        lexer = Lexer(source, file=path)
        tokens = lexer.tokenize()
        parser = Parser(tokens)

        # '#test <fase>' se CONSUME igual que en la ruta normal (_run_source la
        # ejecuta antes de parsear). Sin esto la directiva llegaba a
        # 'parse_directive', que no tiene rama para ella, y un archivo valido se
        # reportaba con PAR020.
        parser.consume_test_directive()

        program = parser.parse()

        # El parser recupera en modo PANICO: ante un error de sintaxis lo anota
        # y SALTA tokens para resincronizar, asi que el AST resultante es "el
        # mejor esfuerzo posible" (ver parse_program). Lo que la recuperacion se
        # trago no esta en la tabla de simbolos, y cada uso de ello se reportaria
        # como no declarado: un solo token suelto producia
        # "'foo' no esta declarado" contra una funcion declarada tres lineas mas
        # abajo. Las fases que LEEN ese AST solo corren si el parseo fue limpio.
        parsed_clean = not lexer.errors and not parser.ctx.errors

        sem_errors: tuple = ()
        notes: list = []
        if parsed_clean:
            resolve_types(program)
            libraries: dict = {}
            _table, sem_errors = analyze(
                program, source_path=path, config=config, notes=notes,
                libraries=libraries)
            if _estado is not None:
                # para '--emit-index': lo que la Semantica ya calculo
                _estado.update(program=program, table=_table, source=source,
                               libraries=libraries)

        extents = _token_extents(tokens)
        for err in (*lexer.errors, *parser.ctx.errors, *sem_errors):
            #to_dict() ya trae la severidad real (critical / panic / ...)
            diagnostics.append(_with_extent(_with_file(err.to_dict(), path), extents))
        for note in notes:
            diagnostics.append(_with_extent({
                "code": note.get("code"), "message": note.get("message"),
                "line": note.get("line"), "column": note.get("column"),
                "file": note.get("file") or path, "severity": "note",
                "phase": "linker"}, extents))
    except Exception as exc:  # noqa: BLE001 - NUNCA romper el canal del editor con un traceback
        # El editor solo ve este mensaje, asi que tiene que bastar para saber
        # QUE fallo: el tipo de la excepcion y el sitio del compilador donde
        # ocurrio (el frame mas profundo del propio proyecto). Un 'ICE000: too
        # many values to unpack' sin mas obliga a reproducirlo a ciegas. Lo
        # arma la misma clase que usa la CLI: un solo formato de ICE.
        ice = InternalCompilerError.desde(exc, phase="canal de diagnosticos",
                                          file=path)
        mensaje = ice.message
        # SURIAX_ICE_TRACEBACK=1 anade la traza completa al mensaje: para
        # depurar sin tener que reproducir el fallo fuera del editor.
        if os.environ.get("SURIAX_ICE_TRACEBACK") == "1":
            mensaje += "\n" + ice.render()
        # linea/columna 1: el editor necesita una posicion donde pintar el
        # diagnostico, aunque un ICE no ocurra en una linea del fuente.
        diagnostics.append({
            "code": ice.code, "message": mensaje,
            "line": 1, "column": 1, "severity": ice.severity,
            "phase": "internal"})

    return _emit({"file": path, "diagnostics": diagnostics})


__all__ = ["emit_stage", "emit_diagnostics", "emit_index", "emit_extensions"]
