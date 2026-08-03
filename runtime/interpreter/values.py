"""Modelo de valores en runtime (secc. 5).

Los primitivos se representan con nativos de Python (``int``/``float``/
``bool``/``str``; ``char`` = ``str`` de 1 code point; ``null`` = ``None``):
cero envoltura en el camino caliente. Solo lo que Python no trae se
representa con clases propias (``__slots__``, comparación explícita):

 - :class:`FunctionValue` — una ``fn`` ligada a su unidad (sus globales).
 - :class:`Namespace` — un import ligado (``const IO = #import IO;``).
 - :class:`StructValue` — instancia de struct: campos como CELDAS (para
   que ``&p.x`` y la escritura a través de punteros tengan destino real).
 - :class:`TypeValue` — un valor del metatipo ``type`` (``const type int8;``).

Los punteros viven en :mod:`memory.pointer` (son instrucción de memoria,
no un valor más).
"""

from __future__ import annotations

from typing import Any, Dict

from .memory.pointer import Cell


class FunctionValue:
    __slots__ = ("unit_alias", "decl")

    def __init__(self, unit_alias: str, decl: Any) -> None:
        self.unit_alias = unit_alias
        self.decl = decl  # message FunctionDecl

    def __repr__(self) -> str:
        return f"<fn {self.decl.name}>"


class Namespace:
    """Un módulo importado, ligado a su unidad HIR."""

    __slots__ = ("alias",)

    def __init__(self, alias: str) -> None:
        self.alias = alias

    def __repr__(self) -> str:
        return f"<module {self.alias}>"


class StructValue:
    __slots__ = ("type_name", "fields")

    def __init__(self, type_name: str, fields: Dict[str, Cell]) -> None:
        self.type_name = type_name
        self.fields = fields

    def __repr__(self) -> str:
        inner = ", ".join(f"{k}={c.value!r}" for k, c in self.fields.items())
        return f"{self.type_name}{{{inner}}}"


class TypeValue:
    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"<type {self.name}>"


class EnumNamespace:
    """El NOMBRE de un enum usado como valor (``Estado.Activo``): expone sus
    items (enteros auto-numerados estilo C, calculados por el loader)."""

    __slots__ = ("name", "items")

    def __init__(self, name: str, items: Dict[str, int]) -> None:
        self.name = name
        self.items = items

    def __repr__(self) -> str:
        return f"<enum {self.name}>"


def format_value(value: Any) -> str:
    """Representación para f-strings y trazas (estable, educativa)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


__all__ = ["FunctionValue", "Namespace", "StructValue", "TypeValue",
           "EnumNamespace", "format_value"]
