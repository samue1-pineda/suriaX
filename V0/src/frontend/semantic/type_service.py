"""Servicio de consulta de tipos: el punto de enganche de la futura Fase 3.

``DESIGN_PRINCIPLES.md`` secc. 7: *"el sistema de tipos no es una fase, es
un servicio"*. Las pasadas (``type_resolver``/``scope_resolver``) NUNCA
comparan ``Type`` a mano: consultan estas funciones. Cuando la Fase 3
(sistema de tipos real: coerciones, genéricos, unificación de nullables)
aterrice, se reemplaza la implementación de ESTE archivo sin tocar a ningún
llamador — ver ``ARQUITECTURA.md`` secc. 5 para la justificación de costo.

Implementación mínima de hoy: identidad estructural estricta (``Type`` es un
dataclass frozen: ``==`` compara estructura), más las dos únicas reglas que
el lenguaje ya necesita (``null`` -> nullable, ``T`` -> ``T?``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Tuple

try:
    from include.types_ast import Type, TypeKind
except ImportError:  # pragma: no cover - ejecucion directa
    from types_ast import Type, TypeKind  # type: ignore

from .symbol_table import Scope, Symbol, SymbolKind

# los tres SymbolKind que nombran un TIPO utilizable en una anotacion.
# 'TYPE' es el tipo nominal opaco de una libreria ('const type int8;'): para
# el consumidor es indistinguible de un struct — de eso se trata.
_TYPE_KINDS = frozenset({SymbolKind.STRUCT, SymbolKind.ENUM, SymbolKind.TYPE})


class TypeLookup(Enum):
    """Resultado de :func:`lookup_type_path` (por que fallo, no solo si fallo)."""
    OK = auto()
    NOT_FOUND = auto()    # el nombre (o la raiz del camino) no existe
    NO_MEMBER = auto()    # el modulo existe pero no publica ese miembro
    NOT_A_TYPE = auto()   # el miembro existe pero no nombra un tipo
    OPAQUE = auto()       # viene de una libreria que no se pudo cargar


@dataclass(slots=True, frozen=True)
class TypeLookupResult:
    status: TypeLookup
    symbol: Optional[Symbol] = None
    owner: str = ""      # prefijo que SI resolvio ('dt' en 'dt.uint8')
    missing: str = ""    # componente que fallo ('uint8')
    available: Tuple[str, ...] = field(default=())  # tipos que el owner si publica


def resolve_nominal(name: str, scope: Scope) -> Optional[Symbol]:
    """Busca ``name`` en el namespace de TIPOS, caminando la cadena de scopes.

    Solo nombres SIMPLES; para los cualificados (``dt.int8``) usa
    :func:`lookup_type_path`, que además explica los fallos.
    """
    return scope.resolve_type(name)


def lookup_type_path(name: str, scope: Scope) -> TypeLookupResult:
    """Resuelve un nombre de tipo, simple (``Punto``) o CUALIFICADO (``dt.int8``).

    Un nombre cualificado atraviesa el namespace de VALORES en su raíz (un
    módulo importado es un valor) y luego desciende por ``Symbol.members``,
    que es un dict plano: cada salto es O(1), sin recorrer scopes.

    Camino rápido: sin puntos —el caso común— no se parte el string ni se
    construye ninguna lista; es una sola búsqueda en la cadena de scopes.
    """
    if "." not in name:
        symbol = scope.resolve_type(name)
        if symbol is None:
            return TypeLookupResult(TypeLookup.NOT_FOUND, missing=name)
        return TypeLookupResult(TypeLookup.OK, symbol)

    parts = name.split(".")
    current = scope.resolve_value(parts[0])
    if current is None:
        return TypeLookupResult(TypeLookup.NOT_FOUND, missing=parts[0])

    for i, part in enumerate(parts[1:], 1):
        members = current.members
        if members is None:
            if current.kind is SymbolKind.IMPORT:
                # import OPACO: la libreria no cargo y ya se reporto una vez.
                # Callar aqui evita una cascada de errores derivados por cada
                # uso del modulo (mismo criterio que 'collect.define_import').
                return TypeLookupResult(TypeLookup.OPAQUE)
            return TypeLookupResult(
                TypeLookup.NO_MEMBER, owner=".".join(parts[:i]), missing=part,
            )
        nxt = members.get(part)
        if nxt is None:
            return TypeLookupResult(
                TypeLookup.NO_MEMBER, owner=".".join(parts[:i]), missing=part,
                available=_type_names(members),
            )
        current = nxt

    if current.kind not in _TYPE_KINDS:
        return TypeLookupResult(TypeLookup.NOT_A_TYPE, current,
                                owner=".".join(parts[:-1]), missing=parts[-1])
    return TypeLookupResult(TypeLookup.OK, current)


def _type_names(members) -> Tuple[str, ...]:
    """Los miembros que nombran un tipo, para el '(disponibles: ...)' del error."""
    return tuple(sorted(
        n for n, s in members.items() if s.kind in _TYPE_KINDS
    ))


def _leaf(name: Optional[str]) -> Optional[str]:
    """El último componente de un nombre nominal (``point.Point`` -> ``Point``)."""
    return name.rsplit(".", 1)[-1] if name else name


def _same_nominal(a: Optional[Type], b: Optional[Type]) -> bool:
    """¿``a`` y ``b`` nombran el MISMO tipo nominal, salvo la calificación?

    ``point.Point`` (calificado como lo ve el consumidor) y ``Point`` (sin
    calificar dentro de la librería que lo declara) son el mismo tipo: se
    comparan por nombre-HOJA. La identidad nominal fina —resuelta hasta la
    declaración, distinguiendo dos ``Point`` de librerías distintas— es cosa
    de la Fase 3; con la resolución solo-por-nombre de hoy, el nombre-hoja es
    la mejor unificación disponible (ver ``types_ast`` cab.).
    """
    return (a is not None and b is not None
            and a.kind is TypeKind.NOMINAL and b.kind is TypeKind.NOMINAL
            and _leaf(a.name) == _leaf(b.name))


def is_assignable(target: Optional[Type], value: Optional[Type]) -> bool:
    """¿Un valor de tipo ``value`` puede asignarse a un binding ``target``?

    Conservador: si alguno de los dos tipos NO se conoce (``None``, p. ej.
    una expresión cuyo tipo aún no se infiere en esta fase), se responde
    ``True`` — esta fase nunca rechaza un programa por información que no
    tiene (cero falsos positivos, ver ``ARQUITECTURA.md`` secc. 4.2).

    HOY: identidad estructural estricta + unificación nominal por nombre-hoja
    (``point.Point`` = ``Point``) + ``T`` asignable a ``T?``.
    FUTURO (Fase 3): coerciones numéricas, genéricos, unificación fina.
    """
    if target is None or value is None:
        return True
    if target == value or _same_nominal(target, value):
        return True
    # T? = T y T? = U?  (envolver en nullable nunca pierde informacion). Se
    # RECURRE al inner para que las coerciones internas compongan: un
    # 'ptr mutable T' es asignable a 'ptr T?' (soltar mutabilidad DENTRO del
    # nullable). 'null' lo cubre 'unify_literal_null', no esta rama.
    if target.kind is TypeKind.NULLABLE:
        inner_value = value.inner if value.kind is TypeKind.NULLABLE else value
        return is_assignable(target.inner, inner_value)
    # modelo de errores por EXCEPCIONES: 'error T' es transparente en la ruta
    # de exito (el throw es control de flujo aparte). Un valor 'error T' se
    # usa como T (lo que devuelve la funcion cuando NO lanza), y un T plano
    # es un 'error T' valido (variante sin error). Se compara el nucleo.
    tv = value.inner if value.kind is TypeKind.ERROR else value
    tt = target.inner if target.kind is TypeKind.ERROR else target
    if (value.kind is TypeKind.ERROR or target.kind is TypeKind.ERROR) \
            and tv is not None and tt is not None and tv == tt:
        return True
    # 'ptr mutable T' es asignable a 'ptr T': SOLTAR el permiso de escritura
    # siempre es seguro (la direccion contraria nunca: ganaria permisos).
    if (
        target.kind is TypeKind.POINTER and value.kind is TypeKind.POINTER
        and value.mut and not target.mut
        and (target.inner == value.inner
             or _same_nominal(target.inner, value.inner))
    ):
        return True
    return False


def unify_literal_null(target: Optional[Type]) -> bool:
    """¿El literal ``null`` es asignable a ``target``?

    HOY: ``null`` unifica con cualquier ``NullableType`` (y con lo
    desconocido, por la misma regla conservadora de :func:`is_assignable`).
    """
    return target is None or target.kind is TypeKind.NULLABLE


__all__ = [
    "resolve_nominal", "lookup_type_path", "TypeLookup", "TypeLookupResult",
    "is_assignable", "unify_literal_null",
]
