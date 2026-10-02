"""Paquetes: una CARPETA de librerías expuesta bajo un solo alias.

Anti-polución de namespaces: el usuario no crea un alias por archivo. La
carpeta tiene un archivo PADRE (``main.libsrx``, o ``<carpeta>.libsrx`` por
compatibilidad) que termina en ``#export package as <alias>``; cada otro
``.libsrx`` de la carpeta es un submódulo::

    lib/io/
    ├── main.libsrx      # '#export package as IO'  (sus decls = raíz)
    ├── print.libsrx     # '#export as print'
    └── console.libsrx   # '#export as console'

**Los nombres los dan los alias, no los archivos** — la carpeta ``io/`` con
``main.libsrx`` dentro se importa como ``IO`` porque eso es lo que declara
su ``#export package as``; ``print.libsrx`` se expone como ``print`` porque
eso declara su propio ``#export``. El nombre de archivo solo localiza en
disco.

``#import IO`` expone ``IO.print.__print__``; ``#import IO.print`` liga solo
``print``; ``#from IO.print #import __print__`` liga solo ese símbolo.
Un solo nivel: sin subpaquetes anidados.
"""

from __future__ import annotations

import os
from typing import List, Optional

from ..frontend.semantic.symbol_table import Symbol, SymbolKind
from . import cache
from .library import LoadedLibrary
from .loader import parse_and_collect
from .resolver import LIBSRX_EXT


def load_package(pkg_name: str, dir_path: str, parent_path: str, config,
                 errors: List, notes, ln: int,
                 col: int) -> Optional[LoadedLibrary]:
    """Carga la carpeta-paquete ``dir_path``: padre + un submódulo por cada
    otro ``.libsrx`` de la carpeta (un solo nivel, sin recursión).

    ``parent_path`` ya viene localizado por ``resolver.find_library`` — no se
    repiten stats aquí. El alias resultante (el del ``#export package as``)
    lo valida ``__init__`` contra el nombre importado.
    """
    parent = parse_and_collect(pkg_name, parent_path, config, errors, notes,
                               ln, col, expect_package=True)
    if parent is None:
        return None

    package = LoadedLibrary(
        alias=parent.alias, path=dir_path,
        values=dict(parent.values), types=dict(parent.types),
        hooks=dict(parent.hooks), dunders=dict(parent.dunders),
    )

    parent_base = os.path.basename(parent_path)
    for entry in sorted(os.listdir(dir_path)):
        if not entry.endswith(LIBSRX_EXT) or entry == parent_base:
            continue
        sub_path = os.path.abspath(os.path.join(dir_path, entry))
        sub = cache.get(sub_path)
        if sub is None:
            if cache.has_failed(sub_path):
                # roto y ya reportado: no se reparsea ni se duplica
                package.fallidos[entry[: -len(LIBSRX_EXT)]] = []
                continue
            # el alias REAL lo declara su '#export'; el stem solo localiza en
            # disco, asi que no se valida contra el nombre de archivo.
            stem = entry[: -len(LIBSRX_EXT)]
            # marcado como 'cargando': si un hermano lo importa mientras
            # tanto y el ciclo vuelve a el, se detecta (ver '_hermano').
            cache.mark_loading(sub_path)
            propios: List = []
            try:
                sub = parse_and_collect(stem, sub_path, config, propios, notes,
                                        ln, col, expect_package=False)
            finally:
                cache.unmark_loading(sub_path)
            if sub is None:
                # sus errores quedan PENDIENTES: se reportan si alguien lo
                # importa, en la línea de ese import
                cache.mark_failed(sub_path)
                package.fallidos[stem] = propios
                continue
            errors.extend(propios)
            cache.put(sub_path, sub)
        # el submodulo es una UNIDAD del programa: se identifica calificado
        # por su paquete ('IO.stdp'), no por su alias suelto ('stdp'), para
        # que dos paquetes con un submodulo homonimo no compartan .phir ni
        # entrada en Image.units. Se fija aqui (unico sitio que conoce al
        # padre) y sobrevive a la cache, que guarda el objeto ya calificado.
        sub.unit = f"{package.alias}.{sub.alias}"
        package.subs[sub.alias] = sub
        # el submodulo se expone como miembro del paquete: IO.print.foo
        package.values[sub.alias] = Symbol(
            name=sub.alias, kind=SymbolKind.IMPORT, ln=ln, col=col,
            members=sub.all_members(),
        )
        # el vocabulario despachado por el COMPILADOR sube al padre: quien
        # importa el paquete lo hereda sin nombrar el submodulo. Las tres
        # tablas viajan juntas — un '__cast__' que se quedara abajo haria que
        # 'cast<dt.int8>(x)' fuera SEM016 en el consumidor aunque la libreria
        # lo declare.
        package.hooks.update(sub.hooks)
        package.dunders.update(sub.dunders)
        package.casts.update(sub.casts)

    return package


__all__ = ["load_package"]
