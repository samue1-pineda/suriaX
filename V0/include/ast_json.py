"""Serializador JSON generico para arboles de dataclasses (AST / AST-tipado).

Recorre cualquier nodo via ``dataclasses.fields()`` en lugar de exigir un
metodo ``to_dict`` por clase: anadir un nodo nuevo a ``ast_nodes.py`` o a
``types_ast.py`` no requiere tocar este archivo. Usado por las directivas
``#test parser`` (AST) y ``#test ast`` (AST-tipado) para volcar la salida.
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Dict, Tuple

# clase -> nombres de campos, resueltos UNA vez (dataclasses.fields()
# reconstruye la tupla de Field en cada llamada; en un volcado de un arbol
# grande eso domina el costo — mismo patron de cache que include/ast_walk.py).
_FIELDS_BY_CLASS: Dict[type, Tuple[str, ...]] = {}


def _class_fields(cls: type) -> Tuple[str, ...]:
    cached = _FIELDS_BY_CLASS.get(cls)
    if cached is None:
        cached = tuple(f.name for f in fields(cls))
        _FIELDS_BY_CLASS[cls] = cached
    return cached


def _encode(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return value.name
    if is_dataclass(value):
        node = {"__node__": type(value).__name__}
        for name in _class_fields(type(value)):
            node[name] = _encode(getattr(value, name))
        return node
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    return repr(value)


def to_dict(node: Any) -> Any:
    """Convierte un nodo (o arbol) de dataclasses a estructuras JSON-nativas."""
    return _encode(node)


def to_json(node: Any, *, indent: int = 2) -> str:
    """Vuelca un nodo (o arbol completo) a texto JSON."""
    return json.dumps(to_dict(node), indent=indent, ensure_ascii=False)


__all__ = ["to_dict", "to_json"]
