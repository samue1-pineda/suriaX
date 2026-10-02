"""La vista de DESUGARING: lo que se escribió y lo que el compilador entiende.

suriaX tiene azúcar en dos fases, y las dos lo deshacen en el árbol:

- el PARSER: ``x += v`` y ``x++`` (``x = x + v``), ``with`` (un bloque con
  sus declaraciones), ``.campo`` (el campo del receptor del ``with``),
  ``int vec.Vector v[n]`` (la llamada a ``make``);
- la SEMÁNTICA: ``throw r`` cede (el ``move`` implícito) y un literal que
  cabe en un ``byte`` o en un ``dt.int8`` se convierte (el ``cast``).

Cada nodo fabricado así lleva de qué azúcar salió (``azucar`` en
``include/ast_nodes.py``). Esa marca NO viaja al HIR —ningún consumidor la
necesita—: esta vista la recoge del árbol y la pone sobre el HIR legible
(``pretty.py``), con la línea del fuente como se escribió encima de cada
sentencia. Lo demás que inserta el compilador y nadie escribe (los ``drop``,
``⟨transfiere⟩``, ``⟨destruye el viejo⟩``, los temporales) ya lo muestra el
HIR legible.
"""

from __future__ import annotations

import io
from typing import List, Optional, Tuple

from include import ast_nodes as ast
from include.ast_walk import walk

#: nodo del AST -> el nombre de su caso en el HIR (el 'oneof node')
_HIR_NODE = {
    ast.Assignment: "assignment",
    ast.Block: "block",
    ast.VarDecl: "var_decl",
    ast.MemberAccess: "member",
    ast.CastExpr: "cast_expr",
    ast.MoveExpr: "move_expr",
}


def sugar_marks(program: ast.Program) -> dict:
    """``(ln, col, nodo del HIR) -> azucar`` de todo lo que salio de uno."""
    marcas = {}
    for nodo in walk(program):
        azucar = getattr(nodo, "azucar", "")
        clave = _HIR_NODE.get(nodo.__class__)
        if azucar and clave is not None:
            marcas[(nodo.ln, nodo.col, clave)] = azucar
    return marcas


def render(program: ast.Program, table, *, source_file: str = "",
           source: Optional[str] = None) -> Tuple[Optional[str], List]:
    """El texto de la vista, o ``(None, errores)`` si el HIR no se pudo
    construir. El programa tiene que haber pasado la Semantica sin errores."""
    from .emmit_IR import build_module
    from .pretty import write_pretty

    module, errores = build_module(program, table, source_file=source_file)
    if module is None:
        return None, errores
    marcas = sugar_marks(program)
    lineas = source.splitlines() if source is not None else []
    salida = io.StringIO()
    salida.write(f"=== desugaring: {len(marcas)} construccion(es) de azucar ===\n")
    for (ln, _col, _nodo), azucar in sorted(marcas.items()):
        salida.write(f"  linea {ln}: {azucar}\n")
    salida.write("\n")
    write_pretty(module, salida, marcas=marcas, lineas=lineas)
    return salida.getvalue(), []


__all__ = ["sugar_marks", "render"]
