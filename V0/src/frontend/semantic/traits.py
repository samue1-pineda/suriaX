"""Traits: contratos definidos por el usuario, verificados por el compilador.

Un ``@trait`` registra un conjunto de firmas de método dunder (``TraitSig``);
un ``@impl(trait)`` sobre un tipo se VERIFICA aquí: el tipo debe proveer cada
método requerido con la firma exacta, sustituyendo el placeholder ``self`` por
el tipo que implementa. Los métodos reales son ``dunder fn`` indexados por
``(tipo, nombre)`` en ``SymbolTable.dunders`` (ver ``collect.py``).

Permite contratos SIN cablearlos en el compilador: el vocabulario (``iterable``,
``sumable``, ...) lo define el usuario; el compilador solo comprueba
conformidad (misma filosofía que los hooks, pero abierta)."""

from __future__ import annotations

from typing import List, Optional, Tuple

try:
    from include import ast_nodes as ast
    from include.types_ast import Type, TypeKind, error_of, nominal, nullable_of, pointer_of
    from error_handler import SemanticError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from types_ast import Type, TypeKind, error_of, nominal, nullable_of, pointer_of  # type: ignore
    import SemanticError  # type: ignore

from .symbol_table import TraitSig


def build_trait_sigs(trait: ast.TraitDecl) -> Tuple[TraitSig, ...]:
    """Firmas requeridas por un trait, con sus tipos ya resueltos por
    ``typed_ast`` (``self`` queda como ``SELF_TYPE``)."""
    return tuple(
        TraitSig(name=m.name, params=tuple(m.param_restypes or ()),
                 ret=m.return_restype)
        for m in trait.methods
    )


def subst_self(t: Optional[Type], impl: Type) -> Optional[Type]:
    """Sustituye el placeholder ``self`` (``SELF_TYPE``) por el tipo ``impl``,
    recursivamente a través de ``ptr``/``?``/``error``. Cualquier otro tipo se
    devuelve intacto (``Type`` es frozen; se reconstruye solo lo necesario)."""
    if t is None:
        return None
    if t.kind is TypeKind.SELF:
        return impl
    if t.kind is TypeKind.POINTER:
        return pointer_of(subst_self(t.inner, impl), mut=t.mut)
    if t.kind is TypeKind.NULLABLE:
        return nullable_of(subst_self(t.inner, impl))
    if t.kind is TypeKind.ERROR:
        return error_of(subst_self(t.inner, impl)) if t.inner is not None else t
    return t


def check_impl(trait_names: List[str], impl_type: str, ctx, ln: int, col: int) -> None:
    """Verifica que ``impl_type`` satisfaga cada trait de ``trait_names``.
    Reporta ``SEM021`` por cada trait no declarado, método faltante o firma
    que no coincide (con ``self`` -> ``impl_type``)."""
    impl = nominal(impl_type)
    for trait_name in trait_names:
        sigs = ctx.table.traits.get(trait_name)
        if sigs is None:
            ctx.error(SemanticError.TraitNotSatisfiedError(
                f"'@impl({trait_name})': el trait '{trait_name}' no está declarado",
                line=ln, column=col,
            ))
            continue
        for sig in sigs:
            dunder = ctx.table.lookup_dunder(impl_type, sig.name)
            if dunder is None:
                ctx.error(SemanticError.TraitNotSatisfiedError(
                    f"'{impl_type}' no implementa '{sig.name}', requerido por "
                    f"el trait '{trait_name}' (declara 'dunder fn {sig.name}"
                    f"({impl_type} ptr self ...)')",
                    line=ln, column=col,
                ))
                continue
            expected_params = tuple(subst_self(p, impl) for p in sig.params)
            expected_ret = subst_self(sig.ret, impl)
            actual_params = tuple(dunder.param_types or ())
            if actual_params != expected_params or dunder.type != expected_ret:
                ctx.error(SemanticError.TraitNotSatisfiedError(
                    f"la firma de '{sig.name}' en '{impl_type}' no coincide con "
                    f"la que exige el trait '{trait_name}'",
                    line=ln, column=col,
                ))


__all__ = ["build_trait_sigs", "subst_self", "check_impl"]
