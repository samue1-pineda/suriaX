"""Estructura de una librería ya cargada (``LoadedLibrary``).

Tipo de datos puro, sin lógica de I/O ni de parseo — el resto del paquete
(``resolver`` -> ``loader`` -> ``packages``) lo produce y ``semantic/`` lo
consume. Aislarlo aquí evita que los tres módulos se importen entre sí solo
para compartir la forma del dato.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover - solo para anotaciones
    from include.types_ast import Type
    from ..frontend.semantic.hooks import HookKind
    from ..frontend.semantic.symbol_table import Symbol


@dataclass(slots=True)
class LoadedLibrary:
    """Una ``.libsrx`` (o paquete) ya parseada y recolectada.

    ``alias`` es el nombre PÚBLICO (el de su ``#export``), que no tiene por
    qué coincidir con el nombre del archivo ni con el de su carpeta: es el
    nombre con el que se importa.

    ``unit`` es el nombre CALIFICADO de la unidad dentro del programa entero:
    igual a ``alias`` para una librería suelta o para el padre de un paquete,
    y ``'<paquete>.<alias>'`` para un submódulo (``'IO.stdp'``). Es la clave
    de la unidad HIR — el nombre de su ``.phir`` y la clave de
    ``Image.units`` — y desambigua dos paquetes que exporten un submódulo
    homónimo, cosa que ``alias`` por sí solo no puede.
    """
    alias: str
    path: str
    unit: str = ""  # '' -> se completa con 'alias' (ver __post_init__)
    # submódulos de un paquete que EXISTEN pero no compilaron, por nombre de
    # archivo (su '#export' no llegó a leerse) -> sus errores, PENDIENTES de
    # reportar. Se reportan cuando alguien importa ese submódulo, en la
    # línea de ESE import (ver '__init__._reporta_fallido'): un paquete se
    # carga entero en su primer import, y un submódulo roto que el programa
    # no usa no debe impedirle compilar. Una lista vacía: ya se reportó.
    fallidos: Dict[str, List] = field(default_factory=dict)
    # exports por nombre: funciones (values) y structs/enums/type (types).
    values: Dict[str, "Symbol"] = field(default_factory=dict)
    types: Dict[str, "Symbol"] = field(default_factory=dict)
    # hooks de tipo declarados por la libreria (se fusionan en el consumidor).
    hooks: Dict[Tuple[str, "HookKind"], "Symbol"] = field(default_factory=dict)
    # conversiones __cast__ declaradas: (Type origen, Type destino) -> Symbol
    # (misma forma que SymbolTable.casts; se fusionan en el consumidor).
    casts: Dict[Tuple["Type", "Type"], "Symbol"] = field(default_factory=dict)
    # metodos de usuario 'dunder fn __x__' declarados: (owner_type, nombre) ->
    # Symbol (misma forma que SymbolTable.dunders; se fusionan en el consumidor
    # para que 'x.__x__()' sobre un tipo de la libreria despache a su cuerpo).
    dunders: Dict[Tuple[str, str], "Symbol"] = field(default_factory=dict)
    # solo paquetes: submodulo -> LoadedLibrary (para '#import io.string').
    subs: Dict[str, "LoadedLibrary"] = field(default_factory=dict)
    # nombres que EXISTEN en la libreria pero no se exportan por ser
    # 'internal' (exclusivos de su archivo). Solo el NOMBRE, nunca el simbolo:
    # sirve para que el diagnostico diga "es internal" en vez de "no existe",
    # que es lo que hacia creer que la libreria estaba rota.
    internos: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # una libreria suelta se identifica por su propio alias; solo
        # 'packages.load_package' califica a sus submodulos.
        if not self.unit:
            self.unit = self.alias

    def member(self, name: str) -> Optional["Symbol"]:
        sym = self.values.get(name)
        return sym if sym is not None else self.types.get(name)

    def all_members(self) -> Dict[str, "Symbol"]:
        merged = dict(self.types)
        merged.update(self.values)
        return merged


__all__ = ["LoadedLibrary"]
