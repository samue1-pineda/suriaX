"""**linker_p** — linker de las librerías nativas ``.libsrx`` de suriaX.

Distinto del linker de objetos del backend y del de ``#extern cpp{}`` (ver
``readme.md``): esto resuelve ``#import``/``#from`` entre unidades del
LENGUAJE, liga sus símbolos y detecta ciclos.

Formas soportadas::

    #import IO;                       -- paquete/archivo cuyo alias es 'IO'
    #import IO.print;                 -- submódulo 'print' del paquete 'IO'
    #from IO.print #import __print__; -- un solo símbolo (cero polución)
    #import util;                     -- util.srcx también vale, con NOTA

Reparto de responsabilidades (un módulo por etapa; ninguno importa al
siguiente hacia atrás):

    resolver.py   nombre -> ruta en disco (search paths, padre de paquete)
    loader.py     ruta -> AST -> símbolos, y contrato '#export'
    packages.py   carpeta-paquete: padre + submódulos por alias
    cache.py      caché por ruta absoluta + guard de imports circulares
    library.py    la estructura 'LoadedLibrary' que produce todo lo anterior

**Regla central**: un módulo se llama como su ALIAS (``#export``), no como
su archivo ni como su carpeta.

Este paquete NO importa ``config/``: ``V0/main.py`` pasa la configuración ya
cargada (``libraries.libsrx_paths``).

**SUBSISTEMA REUSABLE — corte para V1 (deuda anotada, no movida).** La
resolución de librerías es lógica del ECOSISTEMA, no del frontend de V0: V1
(el compilador escrito en suriaX/libsrx) necesitará el MISMO contrato de
``#import``/``#export``/paquetes. Por eso este paquete ya está desacoplado a
propósito — su ÚNICO acoplamiento a V0 es ``error_handler`` (para construir
los ``SemanticError``); todo lo demás (rutas, config) entra por parámetro. Se
mantiene físicamente en ``V0/src/`` por ahora (evitar churn y el choque de
nombre: ``import src`` resuelve a ``V0/src``, y la raíz ``src/`` está
reservada para el código suriaX de V1 — ver ``src/readme.md``). Cuando se
levante V1, este es un candidato claro a extraerse a un paquete top-level
compartido (``linker_p/`` junto a ``runtime/`` y ``config/``): la única
costura a cambiar es de dónde vienen los tipos de error.
"""

from __future__ import annotations

import os
from typing import List, Optional

try:
    from error_handler import SemanticError
except ImportError:  # pragma: no cover - ejecucion directa
    import SemanticError  # type: ignore

from . import cache
from .cache import clear_cache
from .library import LoadedLibrary
from .loader import (NOTE_SRCX_AS_LIB, parse_and_collect, reubicar,
                     validated_alias)
from .packages import load_package
from .resolver import (LIBSRX_EXT, Found, _name_candidates, find_library,
                       search_paths)

_MAX_DOTTED_PARTS = 2  # '<paquete>.<submodulo>'


def load_library(
    lib: str,
    *,
    source_path: Optional[str],
    config: Optional[dict],
    errors: List,
    notes: Optional[List] = None,
    ln: int,
    col: int,
) -> Optional[LoadedLibrary]:
    """Carga (o recupera de la caché) ``lib`` — simple o punteada (``IO.print``).

    Nunca lanza: acumula diagnósticos en ``errors`` (y avisos en ``notes``) y
    devuelve ``None`` si la librería no es usable. ``ln``/``col`` ubican el
    ``#import`` que la pidió.
    """
    parts = lib.split(".")
    root_name = parts[0]
    dotted = len(parts) > 1

    paths = search_paths(source_path, config)
    # un nombre punteado ('IO.print') SOLO lo satisface un paquete: los
    # archivos planos homonimos se ignoran (no ganan por orden de busqueda).
    found = find_library(root_name, paths, packages_only=dotted)
    if found is None:
        what = "paquete" if dotted else ".libsrx, paquete o .srcx"
        errors.append(SemanticError.LibraryNotFoundError(
            f"no se encontró '{root_name}' ({what}) "
            f"(rutas probadas: {', '.join(paths)})",
            line=ln, column=col,
        ))
        return None

    if found.kind == "srcx" and notes is not None:
        notes.append({
            "code": NOTE_SRCX_AS_LIB,
            "message": f"se está usando un .srcx como librería "
                       f"('{os.path.basename(found.path)}'); se recomienda "
                       "usar .libsrx para estas situaciones",
            "file": found.path, "line": ln, "column": col,
        })

    # Un submódulo que importa a un HERMANO ('pk/b.libsrx' -> '#import pk.a')
    # mientras el paquete 'pk' se está cargando: cargar 'pk' otra vez sería un
    # import circular (lo era: SEM010), pero 'b' no necesita el paquete
    # entero, solo el archivo del hermano. Un ciclo REAL entre hermanos
    # ('a' importa 'b' y 'b' importa 'a') se sigue detectando.
    if dotted and found.kind == "package" and cache.is_loading(found.path):
        return _hermano(lib, parts, found, config, errors, notes, ln, col)

    root = _load_cached(root_name, found, config, errors, notes, ln, col)
    if root is None:
        return root
    if not dotted:
        # el paquete ENTERO: también sus submódulos rotos
        for nombre in sorted(root.fallidos):
            _reporta_fallido(root, nombre, errors, ln, col)
        return root
    return _descend(lib, parts, root, errors, ln, col)


def _reporta_fallido(root: LoadedLibrary, nombre: str, errors: List,
                     ln: int, col: int) -> None:
    """Reporta (una vez) los errores de un submódulo que no compiló, con el
    SEM010 en la línea del import que lo pide."""
    pendientes = root.fallidos.get(nombre) or []
    for error in pendientes:
        if isinstance(error, SemanticError.InvalidLibraryError) and \
                not getattr(error, "file", None):
            reubicar(error, ln, col)
    errors.extend(pendientes)
    root.fallidos[nombre] = []


def _hermano(lib: str, parts: List[str], found: Found, config, errors: List,
             notes, ln: int, col: int) -> Optional[LoadedLibrary]:
    """Carga SOLO el submódulo ``parts[1]`` de un paquete que se está cargando."""
    if len(parts) > _MAX_DOTTED_PARTS:
        return _descend(lib, parts, LoadedLibrary(alias=parts[0], path=found.path),
                        errors, ln, col)
    sub_path = None
    for nombre in _name_candidates(parts[1]):
        candidato = os.path.abspath(os.path.join(found.path, nombre + LIBSRX_EXT))
        if os.path.isfile(candidato):
            sub_path = candidato
            break
    if sub_path is None:
        errors.append(SemanticError.UnknownLibraryMemberError(
            f"el paquete '{parts[0]}' no tiene un submódulo '{parts[1]}'",
            line=ln, column=col,
        ))
        return None
    cached = cache.get(sub_path)
    if cached is not None:
        return validated_alias(cached, parts[1], errors, ln, col)
    if cache.has_failed(sub_path):
        return None
    if cache.is_loading(sub_path):
        errors.append(SemanticError.InvalidLibraryError(
            f"import circular entre submódulos de '{parts[0]}': '{lib}' ya se "
            "está cargando (dos submódulos se importan entre sí)",
            line=ln, column=col,
        ))
        return None
    cache.mark_loading(sub_path)
    try:
        sub = parse_and_collect(parts[1], sub_path, config, errors, notes,
                                ln, col, expect_package=False)
    finally:
        cache.unmark_loading(sub_path)
    if sub is None:
        cache.mark_failed(sub_path)
        return None
    # misma identidad de unidad que le dará 'load_package' al terminar
    sub.unit = f"{parts[0]}.{sub.alias}"
    cache.put(sub_path, sub)
    return validated_alias(sub, parts[1], errors, ln, col)


def _descend(lib: str, parts: List[str], root: LoadedLibrary, errors: List,
             ln: int, col: int) -> Optional[LoadedLibrary]:
    """Nombre punteado -> el submódulo del paquete, por ALIAS."""
    if len(parts) > _MAX_DOTTED_PARTS:
        errors.append(SemanticError.InvalidLibraryError(
            f"'{lib}': subpaquetes anidados no soportados todavía "
            "(máximo '<paquete>.<submódulo>')",
            line=ln, column=col,
        ))
        return None
    sub = root.subs.get(parts[1])
    if sub is None and parts[1] in root.fallidos:
        # existe pero no compiló: sus errores, no un "no tiene un submódulo"
        _reporta_fallido(root, parts[1], errors, ln, col)
        return None
    if sub is None:
        errors.append(SemanticError.UnknownLibraryMemberError(
            f"el paquete '{parts[0]}' no tiene un submódulo '{parts[1]}' "
            f"(disponibles: {', '.join(sorted(root.subs)) or 'ninguno'})",
            line=ln, column=col,
        ))
        return None
    return sub


def _load_cached(lib: str, found: Found, config, errors, notes,
                 ln: int, col: int) -> Optional[LoadedLibrary]:
    cached = cache.get(found.path)
    if cached is not None:
        return validated_alias(cached, lib, errors, ln, col)
    if cache.has_failed(found.path):
        # ya se intento y su diagnostico ya se emitio (con la ruta de la lib):
        # ni se reparsea ni se duplica el error. El consumidor recibe None y
        # registra un import OPACO, que corta la cascada de errores derivados.
        return None

    if cache.is_loading(found.path):
        errors.append(SemanticError.InvalidLibraryError(
            f"import circular de librerías detectado al cargar '{lib}'",
            line=ln, column=col,
        ))
        return None

    cache.mark_loading(found.path)
    try:
        if found.kind == "package":
            library = load_package(lib, found.path, found.parent, config,
                                   errors, notes, ln, col)
        else:
            library = parse_and_collect(lib, found.path, config, errors, notes,
                                        ln, col, expect_package=False)
    finally:
        cache.unmark_loading(found.path)

    if library is None:
        cache.mark_failed(found.path)
        return None
    cache.put(found.path, library)
    # la validacion del alias va DESPUES de cachear: el archivo es valido, es
    # este import el que lo llama de otra forma. Asi un import posterior con
    # el nombre correcto lo encuentra en cache en vez de reparsearlo.
    return validated_alias(library, lib, errors, ln, col)


__all__ = [
    "LoadedLibrary", "load_library", "clear_cache", "search_paths",
    "find_library", "NOTE_SRCX_AS_LIB",
]
