"""Recorrido generico y RAPIDO de arboles de dataclasses (AST).

Infraestructura compartida por ``parser/typed_ast.py`` y las pasadas de
``semantic/``: cada pasada es un unico recorrido O(n) del arbol, asi que el
costo del *mecanismo* de recorrido se paga N veces por nodo y domina el
rendimiento del frontend si es lento.

Dos decisiones de rendimiento (medidas, no especulativas):

 - **cache de campos por clase**: ``dataclasses.fields()`` reconstruye la
   tupla de ``Field`` en cada llamada; aqui se resuelve UNA vez por clase y
   se guarda solo el nombre de los campos que pueden contener hijos
   (se excluyen ``ln``/``col``/``restype``/... por tipo en tiempo de cache).
 - **pila explicita en vez de recursion**: un ``Program`` real puede anidar
   expresiones a profundidad arbitraria; la pila explicita evita tanto el
   overhead de frames de Python como el ``RecursionError`` en arboles
   adversariales (el parser ya los tolera, el walker no debe ser el nuevo
   limite).
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Callable, Dict, Iterator, Tuple

try:
    from include.ast_nodes import ASTNode
except ImportError:  # pragma: no cover - ejecucion directa
    from ast_nodes import ASTNode  # type: ignore

# clase -> nombres de campos que pueden contener nodos hijos (str, no Field).
_CHILD_FIELDS: Dict[type, Tuple[str, ...]] = {}

# campos que NUNCA contienen nodos AST: posiciones, tipos resueltos
# (``Type`` es un dataclass frozen SIN hijos AST) y strings estructurales.
_LEAF_FIELDS = frozenset({"ln", "col", "restype", "return_restype", "hook",
                          "param_restypes",
                          # 'drops' son ANOTACIONES (ast.Drop), no hijos: no
                          # heredan de ASTNode y recorrerlas seria escanear una
                          # lista por bloque para descartarla entera.
                          "drops", "temp_drop", "transfers"})


def child_fields(cls: type) -> Tuple[str, ...]:
    """Campos de ``cls`` que pueden contener hijos, resueltos una sola vez."""
    cached = _CHILD_FIELDS.get(cls)
    if cached is None:
        cached = tuple(
            f.name for f in fields(cls) if f.name not in _LEAF_FIELDS
        )
        _CHILD_FIELDS[cls] = cached
    return cached


def walk(root: Any) -> Iterator[ASTNode]:
    """Itera TODOS los nodos ``ASTNode`` del arbol (preorden, iterativo).

    Los valores hoja (str/int/None/Type) se filtran sin visitarse; las
    listas se aplanan. ``root`` mismo se produce primero si es un nodo.
    """
    stack = [root]
    pop = stack.pop
    push = stack.append
    while stack:
        node = pop()
        if isinstance(node, ASTNode):
            yield node
            for name in child_fields(type(node)):
                child = getattr(node, name)
                if child.__class__ is list:
                    # reversed() preserva el orden de preorden con una pila
                    stack.extend(reversed(child))
                elif isinstance(child, ASTNode):
                    push(child)
        elif node.__class__ is list:
            stack.extend(reversed(node))
        # cualquier otro valor (str, int, Interp, Type, None) es hoja: se ignora


def dispatch_walk(root: Any, handlers: Dict[type, Callable[[Any], None]]) -> None:
    """Recorre el arbol invocando ``handlers[type(nodo)]`` si existe.

    Variante de :func:`walk` para pasadas que solo procesan ALGUNAS clases
    de nodo: el lookup por ``type()`` es O(1) (mismo patron de despacho por
    tabla que ``KEYWORDS`` en el lexer y ``_STATEMENT_DISPATCH`` en el
    parser). Los nodos sin handler solo aportan sus hijos.
    """
    get = handlers.get
    for node in walk(root):
        handler = get(node.__class__)
        if handler is not None:
            handler(node)


def deeper_than(root: Any, limit: int) -> Any:
    """El primer nodo que queda a MAS de ``limit`` niveles bajo ``root``.

    ``None`` si el arbol cabe. ``root`` esta en el nivel 1 y cada nodo hijo,
    un nivel mas; las listas no cuentan (son la forma de tener varios hijos).

    Iterativo a proposito: es la funcion que decide si un arbol es demasiado
    profundo para las pasadas recursivas, asi que no puede ser una de ellas.
    Corta en el primer nodo que se pasa — un arbol adversarial no se recorre
    entero para rechazarlo.
    """
    nodes = [root]
    depths = [1]
    while nodes:
        node = nodes.pop()
        depth = depths.pop()
        if node.__class__ is list:
            for child in node:
                if isinstance(child, ASTNode):
                    nodes.append(child)
                    depths.append(depth)
            continue
        if depth > limit:
            return node
        below = depth + 1
        for name in child_fields(type(node)):
            child = getattr(node, name)
            if child.__class__ is list:
                nodes.append(child)
                depths.append(below)
            elif isinstance(child, ASTNode):
                nodes.append(child)
                depths.append(below)
    return None


__all__ = ["walk", "dispatch_walk", "child_fields", "deeper_than"]
