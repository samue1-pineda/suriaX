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


def copy_on_bind(value: Any) -> Any:
    """El valor que se liga a un nombre nuevo, con semántica de VALOR.

    Un ``struct`` es un valor, no una referencia: el único tipo del lenguaje
    que refiere a otro sitio es ``ptr``. Sin esta copia, ``var Caja b = a;``
    dejaba a los dos nombres apuntando al MISMO ``StructValue``, así que
    ``b.v = 99`` cambiaba también ``a`` — y con eso la regla de punteros
    quedaba sin sentido: escribir por un ``ptr`` de solo lectura es
    ``SEM015``, pero bastaba pasar el struct por valor y mutarlo.

    La copia es **superficial en los punteros y profunda en los campos**: se
    crean celdas nuevas para cada campo (por eso mutar la copia no toca al
    original) pero un ``ptr`` guardado en un campo sigue apuntando a lo mismo,
    que es lo que significa un préstamo. Los demás valores del intérprete son
    inmutables (int, float, bool, str, char) o son referencias a propósito
    (punteros, bloques, namespaces): se devuelven tal cual.
    """
    if isinstance(value, StructValue):
        return StructValue(
            value.type_name,
            {name: Cell(copy_on_bind(cell.value), name=name)
             for name, cell in value.fields.items()},
        )
    return value


class TypeValue:
    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"<type {self.name}>"


class EnumNamespace:
    """El NOMBRE de un enum usado como valor (``Estado.Activo``): expone sus
    items (enteros auto-numerados estilo C, calculados por el loader) y, si el
    enum es un tipo SUMA, los constructores de sus variantes con payload."""

    __slots__ = ("name", "items")

    def __init__(self, name: str, items: Dict[str, Any]) -> None:
        self.name = name
        self.items = items

    def __repr__(self) -> str:
        return f"<enum {self.name}>"


class VariantCtor:
    """El CONSTRUCTOR de una variante con payload (``Nodo.Literal``).

    Se invoca como cualquier otra cosa invocable y produce un
    :class:`EnumValue`. Existe como valor propio —en vez de que el intérprete
    reconozca la forma ``Enum.Variante(...)`` en el árbol— porque la variante
    también se nombra PELADA (``Literal(5)``), y entonces no hay ninguna forma
    sintáctica que reconocer: hay un nombre que resuelve a algo invocable.
    """

    __slots__ = ("enum_name", "variant", "arity")

    def __init__(self, enum_name: str, variant: str, arity: int) -> None:
        self.enum_name = enum_name
        self.variant = variant
        self.arity = arity

    def __repr__(self) -> str:
        return f"<variante {self.enum_name}.{self.variant}/{self.arity}>"


class EnumValue:
    """El valor de un enum SUMA: qué variante es, y lo que lleva.

    Los campos son :class:`Cell` como los de un struct, así que el payload
    participa del mismo modelo de memoria que todo lo demás (una variante que
    lleva un puntero lo comparte igual que un campo).
    """

    __slots__ = ("enum_name", "variant", "fields")

    def __init__(self, enum_name: str, variant: str, fields: list) -> None:
        self.enum_name = enum_name
        self.variant = variant
        self.fields = fields

    def __repr__(self) -> str:
        return f"{self.variant}({', '.join(repr(f) for f in self.fields)})"


def format_value(value: Any) -> str:
    """Representación para f-strings y trazas (estable, educativa)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, EnumValue):
        # 'Literal(5)' — la misma forma con la que se escribe en el fuente.
        if not value.fields:
            return value.variant
        dentro = ", ".join(format_value(c.value) for c in value.fields)
        return f"{value.variant}({dentro})"
    return str(value)


__all__ = ["FunctionValue", "Namespace", "StructValue", "TypeValue",
           "copy_on_bind",
           "EnumNamespace", "VariantCtor", "EnumValue", "format_value"]
