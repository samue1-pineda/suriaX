"""``with``: un recurso, un guardián o un receptor con ámbito.

    with_stmt = "with" "(" with_item { "," with_item } ")" block
              | "with" name { "." name } "(" ("var" | "const") type NAME
                    { "," expression } ")" block
    with_item = ("var" | "const") type NAME "=" expression
              | expression

Es AZÚCAR del parser, como la asignación compuesta: sale un ``Block`` con las
declaraciones y, dentro, el cuerpo. No hay un protocolo nuevo (el
``__enter__``/``__exit__`` de Python): lo que hace el ``with`` al salir lo
hace RAII, el ``__free__`` de cada valor, por cualquier camino.

- ``with (var File f = open("x.txt", "w")) { ... }``: un RECURSO con nombre.
- ``with open(var File f, "x.txt", "w") { ... }``: lo mismo escrito como una
  llamada cuyo primer argumento declara el resultado; vale para cualquier
  función, no solo para ``open``.
- ``with (cambiar_idioma("en")) { ... }``: un GUARDIÁN sin nombre. Vive hasta
  el final del bloque y su ``__free__`` deshace el cambio (el *scope guard*
  de C++). Es el único sitio del lenguaje donde un binding no escribe su
  tipo: no hay nombre que anotar, y el tipo es el del valor.
- ``with (ventana) { .ancho = 900; .show(); }``: un RECEPTOR. Dentro del
  bloque, ``.campo`` es un campo (o un método) del valor del ``with``. Con un
  lugar (``ventana``, ``a.b``) el receptor ES ese lugar, sin copiarlo: un
  struct es un valor, y cambiar una copia no cambiaría la ventana.

``.campo`` exige un ``with`` de un solo valor alrededor (``PAR028``): con dos,
no diría de cuál. Con el punto delante un nombre del receptor no se confunde
con una variable local, que es por lo que el ``with`` de nombres pelados de
Pascal (y de JavaScript) cambiaba de significado en silencio.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

try:
    from include import ast_nodes as ast
    from include.t_types import TokenType
    from error_handler import ParseError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from t_types import TokenType  # type: ignore
    import ParseError  # type: ignore

from ..context import ParserContext
from ..cursor import Cursor
from .. import pratt
from ..expressions.led import _copiar, _repetible
from .block import parse_block
from .types import parse_type

# (la declaracion que el 'with' agrega, o None; el receptor de '.campo')
_Item = Tuple[Optional[ast.VarDecl], ast.Expression]


def parse_with_stmt(cursor: Cursor, ctx: ParserContext) -> ast.Block:
    tok = cursor.expect(TokenType.WITH)
    items: List[_Item] = []
    if cursor.check(TokenType.L_PAREN):
        cursor.advance()
        items.append(_item(cursor, ctx))
        while cursor.match(TokenType.COMMA):
            items.append(_item(cursor, ctx))
        cursor.expect(TokenType.R_PAREN)
    else:
        items.append(_forma_de_llamada(cursor, ctx))
    ctx.with_receivers.append(items[0][1] if len(items) == 1 else None)
    try:
        body = parse_block(cursor, ctx)
    finally:
        ctx.with_receivers.pop()
    decls = [decl for decl, _ in items if decl is not None]
    return ast.Block(ln=tok.ln, col=tok.col, statements=[*decls, body],
                     azucar="with: un bloque con sus declaraciones; lo que "
                            "declara muere al cerrarlo")


def _item(cursor: Cursor, ctx: ParserContext) -> _Item:
    start = cursor.peek()
    if cursor.check(TokenType.VAR) or cursor.check(TokenType.CONST):
        qualifier = cursor.advance().lexeme
        type_expr = parse_type(cursor, ctx)
        name = cursor.expect_name()
        cursor.expect(TokenType.ASSIGN)
        value = pratt.parse_expression(cursor, ctx)
        decl = ast.VarDecl(ln=start.ln, col=start.col, qualifier=qualifier,
                           type=type_expr, name=name.lexeme, value=value)
        return decl, ast.Identifier(ln=name.ln, col=name.col, name=name.lexeme)
    value = pratt.parse_expression(cursor, ctx)
    if _repetible(value):
        # un LUGAR: el receptor es el lugar mismo, y nadie nuevo es su dueño
        return None, value
    # un TEMPORAL (un guardian): vive hasta el final del bloque con un nombre
    # que nadie puede escribir ('#' no forma parte de un nombre)
    ctx.with_count += 1
    nombre = f"with#{ctx.with_count}"
    decl = ast.VarDecl(ln=start.ln, col=start.col, qualifier="var", type=None,
                       name=nombre, value=value, inferido=True)
    return decl, ast.Identifier(ln=start.ln, col=start.col, name=nombre)


def _forma_de_llamada(cursor: Cursor, ctx: ParserContext) -> _Item:
    """``open(var File f, "x.txt", "w")`` -> ``var File f = open("x.txt", "w")``."""
    start = cursor.peek()
    first = cursor.expect_name()
    callee: ast.Expression = ast.Identifier(ln=first.ln, col=first.col, name=first.lexeme)
    while cursor.match(TokenType.DOT):
        part = cursor.expect_name()
        callee = ast.MemberAccess(ln=first.ln, col=first.col, obj=callee,
                                  member=part.lexeme)
    cursor.expect(TokenType.L_PAREN)
    if not (cursor.check(TokenType.VAR) or cursor.check(TokenType.CONST)):
        raise ParseError.ExpectedTokenError(
            "'with nombre(...)' declara su resultado en el primer argumento "
            "('with open(var File f, \"x.txt\", \"r\") { }'); sin declaracion, "
            "escribe 'with (expresion) { }'",
            line=cursor.peek().ln, column=cursor.peek().col,
        )
    qualifier = cursor.advance().lexeme
    type_expr = parse_type(cursor, ctx)
    name = cursor.expect_name()
    args: List[ast.Expression] = []
    while cursor.match(TokenType.COMMA):
        args.append(pratt.parse_expression(cursor, ctx))
    cursor.expect(TokenType.R_PAREN)
    call = ast.Call(ln=first.ln, col=first.col, callee=callee, args=args)
    decl = ast.VarDecl(ln=start.ln, col=start.col, qualifier=qualifier,
                       type=type_expr, name=name.lexeme, value=call)
    return decl, ast.Identifier(ln=name.ln, col=name.col, name=name.lexeme)


def parse_receiver_member(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    """``.campo`` dentro de un ``with``: el campo del receptor."""
    dot = cursor.expect(TokenType.DOT)
    name = cursor.expect_name()
    receptor = ctx.with_receivers[-1] if ctx.with_receivers else None
    if receptor is None:
        raise ParseError.WithReceiverError(
            f"'.{name.lexeme}' necesita un 'with' de UN valor alrededor: "
            + ("este 'with' tiene varios y no dice de cual es"
               if ctx.with_receivers else "aqui no hay ninguno"),
            line=dot.ln, column=dot.col,
        )
    return ast.MemberAccess(ln=dot.ln, col=dot.col, obj=_copiar(receptor),
                            member=name.lexeme,
                            azucar=f"'.{name.lexeme}': el campo del receptor del with")


__all__ = ["parse_with_stmt", "parse_receiver_member"]
