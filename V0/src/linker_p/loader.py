"""Carga de UN archivo ``.libsrx``/``.srcx``: lexer -> parser -> AST-tipado
-> recolección de sus declaraciones, y validación del contrato ``#export``.

Contrato del formato: el ÚLTIMO item de nivel superior debe ser un
``#export``. El alias que declara es el nombre público del archivo.

Este módulo NO comprueba que ese alias coincida con el nombre importado: eso
depende del SITIO del import, no del archivo, y lo hace ``__init__`` con
:func:`validated_alias`. La separación importa para la caché: un archivo
correcto importado con el nombre equivocado se cachea igual (es válido), y
un import posterior con el nombre correcto lo encuentra sin reparsear.

Las declaraciones de la librería se recolectan con la MISMA pasada 1 del
consumidor (``semantic/collect.py``) pero en un contexto propio: su scope
global queda AISLADO del que la importa (cero polución de namespaces).
"""

from __future__ import annotations

import os
from typing import List, Optional

try:
    from include import ast_nodes as ast
    from error_handler import SemanticError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    import SemanticError  # type: ignore

from .library import LoadedLibrary

NOTE_SRCX_AS_LIB = "NOTE001"


def validated_alias(library: LoadedLibrary, lib: str, errors: List,
                    ln: int, col: int) -> Optional[LoadedLibrary]:
    """El alias del ``#export`` DEBE coincidir con el nombre importado.

    Regla central del linker: un módulo/paquete se llama como su alias, no
    como su archivo o su carpeta. La comparación tolera el case (``#import
    IO`` liga ``#export package as io``) porque el case de una carpeta no es
    portable entre sistemas de archivos.
    """
    if library.alias == lib or library.alias.lower() == lib.lower():
        return library

    # 'library.path' es un archivo, o la CARPETA si es un paquete: nombrar
    # cual de los dos evita el mensaje ciego "'d_types' exporta 'd_tpypes'".
    base = os.path.basename(library.path)
    what = f"el paquete '{base}/'" if os.path.isdir(library.path) else f"'{base}'"
    errors.append(SemanticError.InvalidLibraryError(
        f"{what} exporta '{library.alias}', no '{lib}' (el alias de "
        "'#export' debe coincidir con el nombre del import)",
        line=ln, column=col,
    ))
    return None


def parse_and_collect(
    lib: str, path: str, config, errors: List, notes, ln: int, col: int,
    *, expect_package: bool,
) -> Optional[LoadedLibrary]:
    """Parsea y recolecta ``path``. ``None`` si el archivo no es una librería
    usable (el diagnóstico ya quedó en ``errors``).

    ``lib`` solo se usa para ubicar diagnósticos: el nombre público que sale
    de aquí es SIEMPRE el del ``#export`` del archivo.
    """
    # imports diferidos: este paquete se usa desde 'semantic/collect.py' y el
    # pipeline de parseo importa medio frontend; cargarlo solo cuando de
    # verdad hay un '#import' que resolver (mismo patron que '#test sem').
    from ..frontend.lexer import source_reader
    from ..frontend.lexer.lexer import Lexer
    from ..frontend.parser.parser import Parser
    from ..frontend.parser.typed_ast import resolve_types

    source = source_reader.read_file(path)
    lexer = Lexer(source, file=path)
    tokens = lexer.tokenize()
    parser = Parser(tokens)
    program = parser.parse()

    if lexer.errors or parser.ctx.errors:
        detail = "; ".join(
            f"{e.code}: {e.message}" for e in (*lexer.errors, *parser.ctx.errors)
        )
        errors.append(SemanticError.InvalidLibraryError(
            f"'{os.path.basename(path)}' contiene errores léxicos/sintácticos: {detail}",
            line=ln, column=col, file=path,
        ))
        return None

    export = _validated_export(program, path, errors, ln, col,
                               expect_package=expect_package)
    if export is None:
        return None

    resolve_types(program)

    from ..frontend.semantic import collect
    from ..frontend.semantic.context import SemanticContext
    from ..frontend.semantic.symbol_table import SymbolTable

    lib_ctx = SemanticContext(SymbolTable(), source_path=path, config=config)
    collect.run(program, lib_ctx)
    if notes is not None and lib_ctx.notes:
        notes.extend(lib_ctx.notes)
    if lib_ctx.errors:
        # las declaraciones invalidas de la lib se reportan UNA vez, aqui,
        # con la ruta de la lib; el consumidor ve de donde vienen.
        for err in lib_ctx.errors:
            err.file = err.file or path
            if err.loc is not None and getattr(err.loc, "file", None) is None:
                err.loc.file = path
        errors.extend(lib_ctx.errors)

    scope = lib_ctx.table.global_scope
    # el nombre publico ES el del '#export': ni el del archivo ni el de su
    # carpeta (regla central del linker, ver 'packages.py').
    #
    # VISIBILIDAD: 'internal' es exclusivo del archivo -> NUNCA se exporta a
    # NINGUN consumidor (se filtra aqui, en el origen). 'private' si viaja en
    # el export; el consumidor decide si lo ve segun este en el mismo paquete
    # ('collect.define_import'). 'public'/None se exportan siempre.
    #
    # Los HOOKS y CONVERSIONES tambien llevan visibilidad (un 'private hook'
    # despacha DENTRO de la libreria pero el consumidor externo no lo conoce):
    # se filtra 'internal' aqui igual que los simbolos. La clave es una tupla
    # ('(owner, kind)' / '(src, dst)') pero el filtro mira el Symbol VALOR, asi
    # que el mismo helper sirve para los tres diccionarios.
    return LoadedLibrary(
        alias=export.alias,
        path=path,
        values=_without_internal(scope.values),
        types=_without_internal(scope.types),
        hooks=_without_internal(lib_ctx.table.hooks),
        casts=_without_internal(lib_ctx.table.casts),
        dunders=_without_internal(lib_ctx.table.dunders),
    )


def _without_internal(symbols: dict) -> dict:
    """Copia de un dict ``clave -> Symbol`` sin los ``internal`` (exclusivos de
    su archivo). Vale para ``{nombre: Symbol}`` y ``{(owner,kind): Symbol}``:
    filtra por el Symbol VALOR, no por la clave."""
    return {key: sym for key, sym in symbols.items()
            if getattr(sym, "visibility", None) != "internal"}


def _validated_export(program: ast.Program, path: str, errors: List,
                      ln: int, col: int, *,
                      expect_package: bool) -> Optional[ast.ExportDirective]:
    export = program.items[-1] if program.items else None
    if not isinstance(export, ast.ExportDirective):
        errors.append(SemanticError.InvalidLibraryError(
            f"'{os.path.basename(path)}' no termina en '#export [as] <alias>' "
            "(obligatorio en toda librería)",
            line=ln, column=col, file=path,
        ))
        return None
    if expect_package and not export.package:
        errors.append(SemanticError.InvalidLibraryError(
            f"'{os.path.basename(path)}' es el padre de un paquete pero no "
            "termina en '#export package as <alias>'",
            line=ln, column=col, file=path,
        ))
        return None
    if not expect_package and export.package:
        errors.append(SemanticError.InvalidLibraryError(
            f"'{os.path.basename(path)}' declara '#export package' pero no es "
            f"el padre de un paquete (debe llamarse 'main.libsrx' o como su carpeta)",
            line=ln, column=col, file=path,
        ))
        return None
    return export


__all__ = ["parse_and_collect", "validated_alias", "NOTE_SRCX_AS_LIB"]
