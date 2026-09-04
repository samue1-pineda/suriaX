"""``decorator_decl`` GENERALIZADO (EBNF secc. 1).

::
    decorator_decl = "@" IDENTIFIER [ "(" [ arg_list ] ")" ]
                     [ visibility ] ( trait_body | [ specifier ] decl )
    arg_list       = ( IDENTIFIER | DUNDER ) { "," ( IDENTIFIER | DUNDER ) }
    decl           = function_decl | struct_decl | enum_decl

El decorador va PRIMERO; la visibilidad y el especificador (si los hay) van
DESPUÉS del decorador (``@impl(iterable) public struct ...``,
``@inline hook fn ...``). Los argumentos entre paréntesis son nombres
(``@impl(iterable)`` -> ``["iterable"]``).

``@trait`` es especial: tiene cuerpo propio (prototipos, no una declaración
normal) y produce un :class:`ast.TraitDecl` en vez de un ``DecoratorDecl``
(ver ``grammar/traits.py``).
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
from .enums import parse_enum_decl
from .functions import parse_function_decl
from .types import parse_type_params
from .prefixes import consume_specifier, consume_visibility
from .structs import parse_struct_decl
from .traits import parse_trait_decl


def parse_decorator_decl(cursor: Cursor, ctx: ParserContext) -> ast.Declaration:
    tok = cursor.advance()  # DECORATOR ya trae el nombre en '.value' (scanners/c_dir.py)
    args = _parse_decorator_args(cursor)
    visibility = consume_visibility(cursor)

    if tok.value == "trait":
        if args:
            raise ParseError.ExpectedTokenError(
                "'@trait' no toma argumentos", line=tok.ln, column=tok.col)
        return parse_trait_decl(cursor, ctx, tok, visibility)

    # '@impl Tipo { fn ... }' (SIN args): bloque de métodos. El de conformidad
    # de trait lleva el trait en paréntesis ('@impl(iterable) struct ...') y cae
    # por el camino de abajo; sin paréntesis, es un bloque de métodos.
    if tok.value == "impl" and not args:
        if visibility is not None:
            raise ParseError.ExpectedTokenError(
                "un bloque '@impl' no lleva visibilidad (ponla en cada método)",
                line=tok.ln, column=tok.col)
        return _parse_impl_block(cursor, ctx, tok)

    specifier = consume_specifier(cursor)
    target = _parse_decorated_target(cursor, ctx, tok, visibility, specifier)
    return ast.DecoratorDecl(ln=tok.ln, col=tok.col, name=tok.value,
                             target=target, args=args, visibility=visibility)


def _receiver_nominal(type_expr) -> Optional[str]:
    """El nombre-hoja del nominal de un ``TypeExpr`` de receptor
    (``Tipo ptr mutable`` -> ``Tipo``), o ``None`` si no es un nominal."""
    node = type_expr
    for _ in range(8):  # cota dura: desenvuelve ptr/nullable anidados
        if isinstance(node, (ast.PointerTypeExpr, ast.NullableTypeExpr)):
            node = node.inner
            continue
        break
    if isinstance(node, ast.NominalTypeExpr) and node.name:
        return node.name.rsplit(".", 1)[-1]
    return None


def _parse_impl_block(cursor: Cursor, ctx: ParserContext,
                      deco_tok) -> ast.ImplDecl:
    """``@impl Tipo { fn m(...) { ... } ... }`` -- métodos de ``Tipo``.

    Cada método lleva RECEPTOR EXPLÍCITO (``Tipo ptr [mutable] self`` como
    primer parámetro) y nombre LLANO; se marca como ``dunder`` de nombre llano
    para registrarse y despacharse como ``x.m(...)`` (misma maquinaria que un
    ``dunder fn``). El parser lo APLANA en ``program.py``."""
    type_tok = cursor.expect_name()
    # '@impl Vector<T>': los parametros del tipo, para que los metodos puedan
    # nombrar 'T' en su firma. Sin esto, un generico solo podia tener metodos
    # si su elemento era un tipo concreto.
    type_params = parse_type_params(cursor, ctx)
    cursor.expect(TokenType.L_BRACE)
    methods: List[ast.FunctionDecl] = []
    while not cursor.check(TokenType.R_BRACE) and not cursor.at_end():
        if not cursor.check(TokenType.FUNCTION):
            nxt = cursor.peek()
            raise ParseError.ExpectedTokenError(
                f"un bloque '@impl' solo contiene métodos ('fn ...'), se "
                f"encontro {nxt.type.name}", line=nxt.ln, column=nxt.col)
        method = parse_function_decl(cursor, ctx)
        if method.dunder is not None:
            raise ParseError.ExpectedTokenError(
                "un método de '@impl' usa nombre llano ('fn push'), no '__x__'",
                line=method.ln, column=method.col)
        if method.body is None:
            raise ParseError.ExpectedTokenError(
                "un método de '@impl' necesita cuerpo, no es un prototipo",
                line=method.ln, column=method.col)
        # el RECEPTOR (primer parámetro) debe ser el tipo del bloque: sin esto,
        # '@impl Box { fn f(Other ptr self) }' registraría 'f' para Other,
        # ignorando el header en silencio.
        owner = type_tok.lexeme.rsplit(".", 1)[-1]
        recv = _receiver_nominal(method.params[0].type) if method.params else None
        if recv != owner:
            raise ParseError.ExpectedTokenError(
                f"el primer parámetro de '{method.name}' debe ser el receptor "
                f"'{type_tok.lexeme} ptr [mutable] <nombre>' (se encontró "
                f"'{recv or 'ninguno'}')", line=method.ln, column=method.col)
        # marcar como método: dunder de nombre llano (owner = 1er param).
        method.dunder = method.name
        method.specifier = "dunder"
        methods.append(method)
    cursor.expect(TokenType.R_BRACE)
    cursor.match(TokenType.SEMICOLON)  # ';' final opcional
    return ast.ImplDecl(ln=deco_tok.ln, col=deco_tok.col,
                        type_name=type_tok.lexeme, methods=methods,
                        type_params=type_params)


def _parse_decorator_args(cursor: Cursor) -> List[str]:
    """``[ "(" [ NAME { "," NAME } ] ")" ]`` -- nombres, o lista vacía."""
    if not cursor.match(TokenType.L_PAREN):
        return []
    args: List[str] = []
    if not cursor.check(TokenType.R_PAREN):
        args.append(cursor.expect_name().lexeme)
        while cursor.match(TokenType.COMMA):
            args.append(cursor.expect_name().lexeme)
    cursor.expect(TokenType.R_PAREN)
    return args


def _parse_decorated_target(cursor: Cursor, ctx: ParserContext, deco_tok,
                            visibility, specifier) -> ast.Declaration:
    if specifier is not None:
        if not cursor.check(TokenType.FUNCTION):
            nxt = cursor.peek()
            raise ParseError.ExpectedTokenError(
                f"'{specifier}' solo precede a 'fn', se encontro {nxt.type.name}",
                line=nxt.ln, column=nxt.col)
        return parse_function_decl(cursor, ctx, visibility=visibility,
                                   specifier=specifier)

    tok = cursor.peek()
    if tok.type is TokenType.FUNCTION:
        return parse_function_decl(cursor, ctx, visibility=visibility)
    if tok.type is TokenType.STRUCT:
        return parse_struct_decl(cursor, ctx, visibility=visibility)
    if tok.type is TokenType.ENUM:
        return parse_enum_decl(cursor, ctx, visibility=visibility)
    raise ParseError.ExpectedTokenError(
        f"un decorador '@{deco_tok.value}' debe preceder a fn/struct/enum, "
        f"se encontro {tok.type.name}", line=tok.ln, column=tok.col)


__all__ = ["parse_decorator_decl"]
