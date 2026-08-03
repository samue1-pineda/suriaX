"""API pública del paquete ``semantic``.

Expone :func:`analyze`: el resto del compilador (HIR) no debe conocer las
pasadas internas ni la tabla de símbolos en detalle, solo el resultado.
"""

from __future__ import annotations

from .hooks import HookKind
from .semantic import analyze
from .symbol_table import Scope, ScopeKind, Symbol, SymbolKind, SymbolTable

__all__ = ["analyze", "SymbolTable", "Scope", "ScopeKind", "Symbol", "SymbolKind", "HookKind"]
