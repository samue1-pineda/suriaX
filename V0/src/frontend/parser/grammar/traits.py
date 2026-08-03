"""``@trait`` -> declaración de un contrato (``TraitDecl``).

Dos formas (ver ``ast_nodes.TraitDecl``):

::
    trait_struct = "@trait" [ visibility ] "struct" "{" { trait_method } "}" IDENTIFIER ";"
    trait_single = "@trait" [ visibility ] [ specifier ] "fn" DUNDER
                   "(" [ type_list ] ")" [ "->" type ] ";"
    trait_method = [ specifier ] "fn" ( IDENTIFIER | DUNDER )
                   "(" [ type_list ] ")" [ "->" type ] ";"
    type_list    = type { "," type }

Un método de trait es un PROTOTIPO: sus parámetros son solo TIPOS (sin nombre),
y uno de ellos suele ser ``self`` (el tipo que hará ``@impl``). El nombre del
método debe ser dunder (``__x__``); la Semántica lo valida.

``@trait`` NO usa el mecanismo general de decoradores (``DecoratorDecl``)
porque su cuerpo tiene gramática propia (prototipos, no campos de datos).
``decorators.parse_decorator_decl`` desvía aquí al ver el nombre ``trait``.
"""

from __future__ import annotations

from typing import List, Optional

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
from .prefixes import consume_specifier
from .types import parse_type


def parse_trait_decl(cursor: Cursor, ctx: ParserContext, deco_tok,
                     visibility: Optional[str]) -> ast.TraitDecl:
    """El ``@trait`` ya fue consumido (``deco_tok``); la visibilidad opcional
    también. Sigue la forma struct (varios métodos) o la suelta (un método)."""
    if cursor.check(TokenType.STRUCT):
        return _parse_trait_struct(cursor, ctx, deco_tok, visibility)
    return _parse_trait_single(cursor, ctx, deco_tok, visibility)


def _parse_trait_struct(cursor: Cursor, ctx: ParserContext, deco_tok,
                        visibility: Optional[str]) -> ast.TraitDecl:
    cursor.expect(TokenType.STRUCT)
    cursor.expect(TokenType.L_BRACE)
    methods: List[ast.TraitMethod] = []
    while not cursor.check(TokenType.R_BRACE) and not cursor.at_end():
        methods.append(_parse_trait_method(cursor, ctx))
    cursor.expect(TokenType.R_BRACE)
    name_tok = cursor.expect_name()
    cursor.expect(TokenType.SEMICOLON)
    return ast.TraitDecl(ln=deco_tok.ln, col=deco_tok.col, name=name_tok.lexeme,
                         methods=methods, visibility=visibility)


def _parse_trait_single(cursor: Cursor, ctx: ParserContext, deco_tok,
                        visibility: Optional[str]) -> ast.TraitDecl:
    """Forma suelta: el trait es UN método y su nombre ES el del método."""
    method = _parse_trait_method(cursor, ctx)
    return ast.TraitDecl(ln=deco_tok.ln, col=deco_tok.col, name=method.name,
                         methods=[method], visibility=visibility)


def _parse_trait_method(cursor: Cursor, ctx: ParserContext) -> ast.TraitMethod:
    """``[ specifier ] "fn" NAME "(" [type_list] ")" [ "->" type ] ";"``.

    El especificador (``hook``/``dunder``) es opcional y no cambia el
    prototipo (un método de trait es un requisito, no una implementación); se
    tolera para que la firma del trait se lea igual que la del método real."""
    consume_specifier(cursor)  # 'dunder'/'hook' opcional y sin efecto aquí
    tok = cursor.expect(TokenType.FUNCTION)
    name_tok = cursor.expect_name()
    cursor.expect(TokenType.L_PAREN)
    params = _parse_type_list(cursor, ctx)
    cursor.expect(TokenType.R_PAREN)
    return_type = None
    if cursor.match(TokenType.ARROW):
        return_type = parse_type(cursor, ctx)
    cursor.expect(TokenType.SEMICOLON)
    return ast.TraitMethod(ln=tok.ln, col=tok.col, name=name_tok.lexeme,
                           params=params, return_type=return_type)


def _parse_type_list(cursor: Cursor, ctx: ParserContext) -> List[ast.TypeExpr]:
    """Parámetros de un prototipo: TIPOS separados por coma, sin nombre."""
    params: List[ast.TypeExpr] = []
    if cursor.check(TokenType.R_PAREN):
        return params
    params.append(parse_type(cursor, ctx))
    while cursor.match(TokenType.COMMA):
        params.append(parse_type(cursor, ctx))
    return params


__all__ = ["parse_trait_decl"]
