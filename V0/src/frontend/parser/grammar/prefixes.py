"""Prefijos opcionales de una declaración: visibilidad y especificador.

Módulo neutro (no importa a ``modifiers``/``decorators``) para que AMBOS lo
usen sin ciclo de imports: ``modifiers.parse_top_level_item`` y
``decorators.parse_decorator_decl`` consumen el mismo prefijo
``[ visibility ] [ hook | dunder ]``.
"""

from __future__ import annotations

from typing import Optional

try:
    from include.t_types import TokenType
except ImportError:  # pragma: no cover - ejecucion directa
    from t_types import TokenType  # type: ignore

from ..cursor import Cursor

VISIBILITY = {
    TokenType.PUBLIC: "public",
    TokenType.PRIVATE: "private",
    TokenType.INTERNAL: "internal",
}
SPECIFIER = {
    TokenType.HOOK: "hook",
    TokenType.DUNDER_KW: "dunder",
}


def consume_visibility(cursor: Cursor) -> Optional[str]:
    """Consume ``public``/``private``/``internal`` si está; si no, ``None``."""
    vis = VISIBILITY.get(cursor.peek().type)
    if vis is not None:
        cursor.advance()
    return vis


def consume_specifier(cursor: Cursor) -> Optional[str]:
    """Consume ``hook``/``dunder`` si está; si no, ``None``."""
    spec = SPECIFIER.get(cursor.peek().type)
    if spec is not None:
        cursor.advance()
    return spec


__all__ = ["VISIBILITY", "SPECIFIER", "consume_visibility", "consume_specifier"]
