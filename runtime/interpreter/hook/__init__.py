"""Despacho de hooks de tipo en runtime (índices O(1) sobre el HIR)."""

from .dispatch import BoundFunction, index_casts, index_hooks, type_key

__all__ = ["BoundFunction", "index_casts", "index_hooks", "type_key"]
