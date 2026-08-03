"""Punto de entrada gramatical: ``program = { top_level } EOF`` (EBNF secc. 1).

El bucle raiz y la recuperacion de errores viven aqui; el despacho de cada
item y su prefijo de modificadores (visibilidad, ``hook``/``dunder``) los dueña
``grammar/modifiers.py`` (``top_level = [ visibility ] [ hook | dunder ]
declaration``). ``extern_block`` se despacha dentro de
``directives.parse_directive`` (mismo token ``DIRECTIVE``).
"""

from __future__ import annotations

from typing import List

try:
    from include import ast_nodes as ast
    from error_handler import ParseError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    import ParseError  # type: ignore

from ..context import ParserContext
from ..cursor import Cursor
from ..recovery import synchronize
from .modifiers import parse_top_level_item


def parse_program(cursor: Cursor, ctx: ParserContext) -> ast.Program:
    """Analiza el flujo completo. Nunca lanza: los errores de sintaxis se
    acumulan en ``ctx.errors`` (modo panico, ver ``recovery.synchronize``) y
    el AST devuelto es el mejor esfuerzo posible con lo que sí se pudo parsear.

    Tambien captura ``RecursionError``: el parser es de descenso recursivo
    (parentesis/prefijos unarios anidados consumen un nivel de pila de Python
    por nivel de anidamiento), asi que una entrada con anidamiento extremo
    -- adversarial o generada -- puede agotar la pila. Se convierte a
    ``ParseError.ExpressionTooDeepError`` en el mismo punto de recuperacion
    en vez de dejar que el proceso termine con una excepcion no controlada.
    Cuando esto ocurre la pila ya se desenrollo por completo (la excepcion se
    propaga liberando cada marco), asi que hay margen de sobra para construir
    el error y llamar a ``synchronize`` con normalidad.
    """
    tok = cursor.peek()
    items: List[ast.ASTNode] = []

    while not cursor.at_end():
        start_pos = cursor.pos
        try:
            item = parse_top_level_item(cursor, ctx)
            # '@impl Tipo { ... }' se APLANA en sus métodos (dunders de nombre
            # llano): las fases posteriores solo ven FunctionDecl, nunca ImplDecl.
            if isinstance(item, ast.ImplDecl):
                items.extend(item.methods)
            else:
                items.append(item)
        except ParseError.ParseError as exc:
            ctx.errors.append(exc)
            synchronize(cursor, start_pos)
        except RecursionError:
            err_tok = cursor.peek()
            ctx.errors.append(ParseError.ExpressionTooDeepError(
                "construccion anidada excede la profundidad soportada por el parser",
                line=err_tok.ln, column=err_tok.col,
            ))
            synchronize(cursor, start_pos)

    return ast.Program(ln=tok.ln, col=tok.col, items=items)


__all__ = ["parse_program"]
