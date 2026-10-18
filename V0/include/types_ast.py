"""Tipos RESUELTOS de suriaX (fase AST-tipado).

Distinto de ``ast_nodes.TypeExpr``: ``TypeExpr`` es la anotacion tal como se
escribio en el codigo fuente (sintactica, sin resolver); :class:`Type` es la
representacion estructurada a la que ``parser/typed_ast.py`` la resuelve.

No hay resolucion de simbolos aqui (eso es Semantica / Fase 4): un tipo
nominal (``NOMINAL``) se resuelve solo hasta *nombre*, no hasta la declaracion
``struct``/``enum`` a la que apunta.

Mismo patron que ``include/t_types.py``: dataclass plano con un discriminante
(``kind``) en lugar de una jerarquia de subclases, y tablas O(1) construidas
una sola vez al importar.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple


class TypeKind(Enum):
    VOID = auto()
    BOOL = auto()
    INT = auto()
    FLOAT = auto()
    CHAR = auto()
    STR = auto()
    POINTER = auto()    # 'inner' = tipo apuntado
    NULLABLE = auto()   # 'inner' = tipo envuelto
    NOMINAL = auto()     # 'name'  = nombre del tipo definido por el usuario
    META = auto()        # 'type': el tipo de un TIPO (ver META_TYPE)
    ERROR = auto()       # 'error T' (inner) o 'error' solo (inner None): union T-o-error
    SELF = auto()        # placeholder 'self' en la firma de un trait (ver SELF_TYPE)
    BYTE = auto()        # 'byte': entero SIN signo de 8 bits (0..255)
    FUNCTION = auto()    # 'fn(A, B) -> R': 'args' = parametros, 'inner' = retorno


@dataclass(slots=True, frozen=True)
class Type:
    """Tipo resuelto. Hashable e inmutable: reutilizable como clave/valor
    compartido (los primitivos son singletons, ver :data:`PRIMITIVE_TYPES`).

    ``mut`` solo aplica a ``POINTER``: ``ptr mutable T`` (se puede escribir
    a traves del puntero) vs ``ptr T`` (solo lectura a traves de el).
    Participa de la igualdad: ``ptr mutable T != ptr T`` — la coercion
    segura (mutable -> no-mutable) la decide ``semantic/type_service.py``,
    nunca una comparacion directa.

    ``args`` solo aplica a ``NOMINAL``: son los ARGUMENTOS DE TIPO de un
    generico (``Vector<int>``). Participan de la igualdad, que es todo el
    punto: ``Vector<int>`` y ``Vector<str>`` son tipos DISTINTOS y el
    compilador no los puede confundir. Una tupla (no lista) para que ``Type``
    siga siendo hashable — se usa como clave en la tabla de conversiones y en
    el pool de tipos del HIR.

    Un tipo ``FUNCTION`` (``fn(int, str) -> bool``) REUSA los dos campos en
    vez de añadir otros: ``args`` son los tipos de sus PARAMETROS, en orden, e
    ``inner`` el de su RETORNO (``void`` si no devuelve nada). Es la misma
    forma que tiene en el HIR, y por eso todo lo que ya recorre ``args`` e
    ``inner`` (igualdad, hash, el pool de tipos) lo trata bien sin saber que
    existe. Lo que SI tiene que saberlo es quien reconstruye un tipo por
    partes (sustituir, canonicalizar): un ``Type(t.kind, inner=...)`` sin
    ``args`` perderia los parametros.
    """

    kind: TypeKind
    name: Optional[str] = None
    inner: Optional["Type"] = None
    mut: bool = False
    args: Tuple["Type", ...] = ()

    def __repr__(self) -> str:
        """El tipo escrito como se escribe en el LENGUAJE (``C ptr mutable``).

        Es el texto de todos los diagnosticos, del indice del editor y de los
        volcados. Fue prefijo (``ptr mutable C``) por historia del frontend,
        y por eso habia dos formateadores que no coincidian: los mensajes que
        usaban este hablaban al reves de como se escribe el codigo."""
        if self.kind is TypeKind.FUNCTION:
            params = ", ".join(repr(a) for a in self.args)
            return f"fn({params}) -> {self.inner!r}"
        if self.kind is TypeKind.POINTER:
            return f"{_parenthesized(self.inner)} ptr mutable" if self.mut \
                else f"{_parenthesized(self.inner)} ptr"
        if self.kind is TypeKind.NULLABLE:
            return f"{_parenthesized(self.inner)}?"
        if self.kind is TypeKind.NOMINAL:
            if self.args:
                return f"{self.name}<{', '.join(repr(a) for a in self.args)}>"
            return f"{self.name}"
        if self.kind is TypeKind.ERROR:
            return f"error {_parenthesized(self.inner)}" \
                if self.inner is not None else "error"
        if self.kind is TypeKind.SELF:
            return "self"
        return self.kind.name.lower()


def _parenthesized(t: Optional[Type]) -> str:
    """``repr`` de ``t``, entre parentesis si es un tipo funcion.

    Un sufijo escrito tras ``fn(int) -> int`` se pega al RETORNO
    (``fn(int) -> int?`` devuelve un ``int?``), asi que el tipo funcion
    envuelto se escribe con parentesis: ``(fn(int) -> int)?``. Sin ellos el
    texto de un diagnostico describiria otro tipo."""
    if t is not None and t.kind is TypeKind.FUNCTION:
        return f"({t!r})"
    return repr(t)


# --- tabla O(1) de tipos primitivos, construida una sola vez al importar ---
PRIMITIVE_TYPES: dict[str, Type] = {
    "void": Type(TypeKind.VOID),
    "bool": Type(TypeKind.BOOL),
    "int": Type(TypeKind.INT),
    "float": Type(TypeKind.FLOAT),
    "char": Type(TypeKind.CHAR),
    "str": Type(TypeKind.STR),
    "byte": Type(TypeKind.BYTE),
}

#: El METATIPO: el tipo que tiene un TIPO cuando se usa como valor.
#:
#: ``const type int8;`` declara un tipo nominal OPACO llamado ``int8`` — el
#: binding es de tipo ``type``, su valor ES un tipo. Simetricamente,
#: ``fn _block_def(int len) -> type`` es una funcion que DEVUELVE un tipo.
#: Singleton como los primitivos: ``Type`` es frozen, no hay nada que
#: distinga dos instancias de ``type``.
META_TYPE: Type = Type(TypeKind.META)

#: El placeholder ``self`` en la firma de un metodo de trait: representa "el
#: tipo que hara ``@impl``". Al verificar conformidad se SUSTITUYE por el
#: nominal del tipo que implementa (ver ``semantic/traits.py``). No es un tipo
#: usable como valor: solo vive dentro de un prototipo de trait.
SELF_TYPE: Type = Type(TypeKind.SELF)

# tipo de cada literal de expresion (usado por 'parser/typed_ast.py')
LITERAL_TYPES: dict[str, Type] = {
    "int": PRIMITIVE_TYPES["int"],
    "float": PRIMITIVE_TYPES["float"],
    "str": PRIMITIVE_TYPES["str"],
    "char": PRIMITIVE_TYPES["char"],
    "bool": PRIMITIVE_TYPES["bool"],
    # 'null' no tiene tipo propio: depende del nullable al que se asigne.
    # Esa unificacion es semantica, no de esta fase (AST-tipado).
}


def pointer_of(inner: Type, *, mut: bool = False) -> Type:
    return Type(TypeKind.POINTER, inner=inner, mut=mut)


def nullable_of(inner: Type) -> Type:
    return Type(TypeKind.NULLABLE, inner=inner)


def nominal(name: str, args: Tuple[Type, ...] = ()) -> Type:
    """Tipo nominal, opcionalmente con ARGUMENTOS DE TIPO (``Vector<int>``)."""
    return Type(TypeKind.NOMINAL, name=name, args=args)


def error_of(inner: Optional[Type]) -> Type:
    """``error T`` (inner) o ``error`` a secas (inner ``None``)."""
    return Type(TypeKind.ERROR, inner=inner)


def function_of(params: Tuple[Type, ...], ret: Type) -> Type:
    """``fn(params) -> ret``: el tipo de una funcion usada como VALOR."""
    return Type(TypeKind.FUNCTION, inner=ret, args=tuple(params))


def is_function(t: Optional[Type]) -> bool:
    """¿``t`` es un tipo funcion (sin envolver)?"""
    return t is not None and t.kind is TypeKind.FUNCTION


def is_meta(t: Optional[Type]) -> bool:
    """¿``t`` es el metatipo ``type``? (helper para no comparar ``kind`` a mano)"""
    return t is not None and t.kind is TypeKind.META


__all__ = [
    "TypeKind",
    "Type",
    "PRIMITIVE_TYPES",
    "LITERAL_TYPES",
    "META_TYPE",
    "SELF_TYPE",
    "pointer_of",
    "nullable_of",
    "nominal",
    "error_of",
    "function_of",
    "is_function",
    "is_meta",
]
