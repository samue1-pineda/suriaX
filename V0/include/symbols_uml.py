"""Tabla de símbolos -> diagrama de clases **Mermaid** (``--dump-symbols-table``).

Proyecta la ``SymbolTable`` (post-Semántica) a un ``classDiagram`` de Mermaid,
el formato que la web de ``/documentation`` renderiza. La correspondencia:

  * ``struct``  -> una clase con sus CAMPOS (atributos) y sus MÉTODOS
    (los ``dunder``/``@impl`` y los ``hook`` cuyo dueño es ese tipo);
  * ``enum``    -> una clase ``<<enumeration>>`` con sus items;
  * ``const type`` opaco -> una clase ``<<type>>`` sin miembros;
  * un campo cuyo tipo es OTRO tipo nominal conocido -> una asociación
    ``Dueño --> TipoCampo : campo``.

No participa de ningún camino caliente: se materializa solo cuando se pide el
volcado. No compara ``Type`` a mano ni depende del HIR (solo de la tabla).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

try:
    from include.types_ast import Type, TypeKind
    from src.frontend.semantic.symbol_table import (Symbol, SymbolKind,
                                                    SymbolTable)
except ImportError:  # pragma: no cover - ejecucion directa
    from types_ast import Type, TypeKind  # type: ignore
    from frontend.semantic.symbol_table import (Symbol, SymbolKind,  # type: ignore
                                                SymbolTable)

# caracteres que rompen el cuerpo de una clase Mermaid; se neutralizan.
_UNSAFE = str.maketrans({"~": "_", "<": "(", ">": ")", "\n": " ", "\r": " "})
# prefijo de módulo de un nominal cualificado ('vec.Vector' -> 'Vector'): más
# legible en el diagrama y evita que el '.' confunda al parser de Mermaid.
_QUALIFIER = re.compile(r"[A-Za-z_]\w*\.")


def _fmt_type(t: Optional[Type]) -> str:
    """``Type`` -> texto seguro para Mermaid (``int``, ``int ptr mutable``),
    con los nominales por su nombre-HOJA (sin el módulo que los califica)."""
    if t is None:
        return "?"
    return _QUALIFIER.sub("", repr(t).translate(_UNSAFE))


def _leaf_nominal(t: Optional[Type]) -> Optional[str]:
    """El nombre-hoja si ``t`` (o su interior de ptr/nullable) es nominal."""
    seen = 0
    while t is not None and t.kind in (TypeKind.POINTER, TypeKind.NULLABLE) \
            and seen < 8:
        t = t.inner
        seen += 1
    if t is not None and t.kind is TypeKind.NOMINAL and t.name:
        return t.name.rsplit(".", 1)[-1]
    return None


def _method_line(sym: Symbol) -> str:
    """Firma de un método para el cuerpo de la clase: ``+name(t1, t2) ret``.

    Salta el RECEPTOR (primer parámetro, el ``T ptr self``): en un diagrama de
    clases el receptor es implícito."""
    params = sym.param_types or ()
    shown = params[1:] if params else ()
    args = ", ".join(_fmt_type(p) for p in shown)
    ret = _fmt_type(sym.type)
    return f"+{sym.name}({args}) {ret}"


def _methods_by_owner(table: SymbolTable) -> Dict[str, List[str]]:
    """``owner_type (hoja) -> [líneas de método]`` desde dunders y hooks."""
    out: Dict[str, List[str]] = {}
    for (owner, _name), sym in table.dunders.items():
        out.setdefault(owner.rsplit(".", 1)[-1], []).append(_method_line(sym))
    for (owner, _kind), sym in table.hooks.items():
        out.setdefault(owner.rsplit(".", 1)[-1], []).append(_method_line(sym))
    return out


def symbol_table_to_mermaid(table: SymbolTable) -> str:
    """La tabla de símbolos como un ``classDiagram`` de Mermaid (texto)."""
    types = table.global_scope.types
    methods = _methods_by_owner(table)
    lines: List[str] = ["classDiagram"]
    relations: List[str] = []
    free_fns: List[str] = []

    for name in sorted(types):
        sym = types[name]
        body: List[str] = []
        stereotype: Optional[str] = None

        if sym.kind is SymbolKind.ENUM:
            stereotype = "enumeration"
            for item in (sym.members or {}):
                body.append(item)
        elif sym.kind is SymbolKind.STRUCT:
            for fname, fsym in (sym.members or {}).items():
                body.append(f"+{_fmt_type(fsym.type)} {fname}")
                target = _leaf_nominal(fsym.type)
                if target is not None and target != name:
                    relations.append(f"  {name} --> {target} : {fname}")
        elif sym.kind is SymbolKind.TYPE:
            stereotype = "type"

        body.extend(methods.get(name, ()))

        lines.append(f"  class {name} {{")
        if stereotype is not None:
            lines.append(f"    <<{stereotype}>>")
        for entry in body:
            lines.append(f"    {entry}")
        lines.append("  }")

    # funciones LIBRES (no métodos) en una caja aparte, para no perderlas.
    for vname in sorted(table.global_scope.values):
        vsym = table.global_scope.values[vname]
        if vsym.kind is SymbolKind.FUNCTION:
            args = ", ".join(_fmt_type(p) for p in (vsym.param_types or ()))
            free_fns.append(f"+{vname}({args}) {_fmt_type(vsym.type)}")
    if free_fns:
        lines.append('  class functions {')
        lines.append("    <<module>>")
        for entry in free_fns:
            lines.append(f"    {entry}")
        lines.append("  }")

    lines.extend(relations)
    return "\n".join(lines) + "\n"


__all__ = ["symbol_table_to_mermaid"]
