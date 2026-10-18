"""Cotas de los parametros de tipo (``<T: Ord + Contrato>``).

Una COTA dice que tiene un ``T``: dentro del generico, lo que promete se puede
usar y se comprueba UNA vez, en la definicion; en cada instancia, el
argumento de tipo tiene que cumplirla, y si no, el error sale en la llamada.
Sin cota todo sigue como antes (``SEM043`` y la comprobacion por instancia).

Una cota nombra una de dos cosas:

- un **trait del usuario** (``@trait struct { ... } Contrato;``), que se
  cumple de forma EXPLICITA: el tipo lo declara con ``@impl(Contrato)``;
- un **concepto nativo** (``Eq``, ``Ord``, ``Hash``, ``Print``), que se
  cumple SOLO, con las reglas que el lenguaje ya aplica a un tipo concreto
  (decision del mantenedor para el paso 4).

**Donde viven los nombres de los conceptos.** Lo decidido era "en la
libreria", pero un concepto no se puede escribir en suriaX (no hay como decir
"se cumple solo"), y ponerlos en un paquete obligaria a importar algo para
escribir ``T: Ord``. Son nombres PREDEFINIDOS que solo existen en posicion de
cota: no son palabras reservadas ni ocupan el espacio de tipos ni el de
valores (un ``struct Ord`` sigue siendo valido). Si el archivo declara un
trait con el mismo nombre, manda el trait —la misma regla que una ``fn print``
del usuario frente al hook—, asi que nunca chocan con un nombre propio.

Este modulo solo RESUELVE lo escrito; que un tipo cumpla una cota lo decide
``scope_resolver`` (necesita el scope y los hooks).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

try:
    from error_handler import SemanticError
except ImportError:  # pragma: no cover - ejecucion directa
    import SemanticError  # type: ignore

#: los conceptos nativos, en el orden en que se listan en los mensajes
NATIVE_CONCEPTS = ("Eq", "Ord", "Hash", "Print")

CONCEPT = "concept"
TRAIT = "trait"


@dataclass(frozen=True, slots=True)
class BoundRef:
    """Una cota ya resuelta. ``name`` es el concepto (``"Ord"``) o el nombre
    CANONICO del trait (``"Forma"``, ``"geom.Forma"`` en una libreria): es su
    identidad, la misma que guarda el tipo que lo implementa."""
    kind: str
    name: str

    @property
    def written(self) -> str:
        """Como se escribe en el fuente (sin la unidad)."""
        return self.name.rsplit(".", 1)[-1]


def bounds_text(refs: Iterable[BoundRef]) -> str:
    """``Ord + Forma``: como se leen en una firma."""
    return " + ".join(r.written for r in refs)


def resolve(declared: Dict[str, list], params: List[str], ctx, owner: str,
            reported: set) -> Dict[str, Tuple[BoundRef, ...]]:
    """Las cotas escritas de una declaracion, resueltas.

    ``declared`` es ``{parametro: [ast.TypeBound, ...]}`` tal como lo dejo el
    parser. Una cota que no nombra un trait de este archivo ni un concepto es
    ``SEM021`` (la misma familia que ``@impl(X)`` con un trait inexistente),
    una sola vez por cota escrita: ``reported`` guarda las ya dichas, porque
    las de un ``@impl Tipo<T: X>`` viajan en cada uno de sus metodos.
    """
    resolved: Dict[str, Tuple[BoundRef, ...]] = {}
    for param in params:
        refs: List[BoundRef] = []
        for bound in declared.get(param, ()):
            ref = _resolve_one(bound, param, ctx, owner, reported)
            if ref is not None and ref not in refs:
                refs.append(ref)
        if refs:
            resolved[param] = tuple(refs)
    return resolved


def _resolve_one(bound, param: str, ctx, owner: str, reported: set):
    name = bound.name
    if "." not in name:
        if name in ctx.table.traits:
            return BoundRef(TRAIT, ctx.qualify(name))
        if name in NATIVE_CONCEPTS:
            return BoundRef(CONCEPT, name)
    if id(bound) in reported:
        return None
    reported.add(id(bound))
    if "." in name:
        why = ("no se puede usar: una cota nombra un trait de ESTE archivo o "
               "un concepto, y un trait de otra libreria todavia no")
    else:
        why = ("no es un trait declarado en este archivo ni un concepto "
               f"nativo ({', '.join(NATIVE_CONCEPTS)})")
    ctx.error(SemanticError.TraitNotSatisfiedError(
        f"la cota '{name}' de '{param}' en '{owner}' {why}",
        line=bound.ln, column=bound.col,
    ))
    return None


__all__ = ["NATIVE_CONCEPTS", "CONCEPT", "TRAIT", "BoundRef", "bounds_text",
           "resolve"]
