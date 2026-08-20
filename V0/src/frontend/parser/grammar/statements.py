"""``statement`` dispatch + ``var_decl`` + ``type_decl`` + ``expr_stmt``
(EBNF secc. 2).

::
    statement = var_decl | type_decl | region_stmt | if_stmt | while_stmt
              | match_stmt | return_stmt | break_stmt | continue_stmt
              | move_stmt | free_stmt | expr_stmt
    var_decl  = [ qualifier ] type IDENTIFIER [ "=" expression ] ";"
    type_decl = [ qualifier ] "type" IDENTIFIER [ "=" expression ] ";"
    qualifier = "const" | "var"          -- sin qualifier = 'var' (estilo C)
    expr_stmt = expression ";"

``var_decl`` y ``type_decl`` comparten prefijo (``[qualifier]``) y se
distinguen con UN token: ``type`` tras el qualifier arranca un ``type_decl``
(``const type int8;`` declara el tipo ``int8``, no una variable llamada
``int8``). Ver ``ast_nodes.TypeDecl``.

``mutable`` YA NO es un qualifier de variable (decisión de diseño): quedó
reservado para los tipos puntero (``ptr mutable T``, ver ``types.py``). Un
``mutable int x`` produce un ParseError con la sugerencia de usar ``var``.

Despacho O(1) por diccionario ``TokenType -> handler`` (mismo patron que
``include.t_types.KEYWORDS``), salvo un caso: un ``statement`` que empieza
con ``IDENTIFIER`` es ambiguo entre TRES formas -- ``var_decl`` de tipo
nominal (``Punto p = ...;``), ``ImportBinding`` sin qualifier
(``IO = #import IO;``, ver ``ast_nodes.ImportBinding``) y ``expr_stmt``
(``foo();``, ``i = i + 1;``). Se resuelve con lookahead acotado -- sin
backtracking, ver ARQUITECTURA.md secc. 1 -- que NO consume tokens.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

try:
    from include import ast_nodes as ast
    from include.t_types import TokenType
    from error_handler import ParseError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from t_types import TokenType  # type: ignore
    import ParseError  # type: ignore

from .. import pratt
from ..context import ParserContext
from ..cursor import Cursor
from .control_flow import (
    parse_break_stmt, parse_continue_stmt, parse_if_stmt, parse_match_stmt,
    parse_return_stmt, parse_while_stmt,
)
from .directives import parse_from_dir, parse_import_dir
from .errors import parse_throw_stmt, parse_try_stmt
from .memory import parse_free_stmt, parse_move_stmt
from .types import parse_type, parse_type_params


def parse_statement(cursor: Cursor, ctx: ParserContext,
                    visibility: Optional[str] = None) -> ast.Statement:
    """Despacha una sentencia. ``visibility`` solo lo pasa
    ``grammar/modifiers.py`` para un binding de NIVEL SUPERIOR
    (``public const int MAX = 10;``); se adjunta al nodo si es una declaracion
    que la admite (``VarDecl``/``TypeDecl``/``ImportBinding``) y es un error en
    cualquier otra forma. Dentro de un bloque siempre llega ``None`` (los
    tokens de visibilidad tienen su propio handler de mal uso)."""
    start = cursor.peek()
    node = _dispatch_statement(cursor, ctx)
    if visibility is not None:
        if isinstance(node, (ast.VarDecl, ast.TypeDecl, ast.ImportBinding)):
            node.visibility = visibility
        else:
            raise ParseError.InvalidStatementError(
                "la visibilidad (public/private/internal) solo aplica a "
                "declaraciones (fn, struct, enum o un binding)",
                line=start.ln, column=start.col,
            )
    return node


def _dispatch_statement(cursor: Cursor, ctx: ParserContext) -> ast.Statement:
    tok = cursor.peek()
    if tok.type is TokenType.IDENTIFIER or tok.type is TokenType.DUNDER:
        # Un tipo nominal puede llamarse '__x__' (ver Cursor.expect_name):
        # 'DUNDER' arranca la misma ambiguedad que 'IDENTIFIER' aqui.
        #
        # 'IDENTIFIER = #import/#from ...;' SIN qualifier (ver ast_nodes.ImportBinding):
        # debe probarse ANTES que 'parse_var_decl' porque ese solo se alcanza
        # via CONST/MUTABLE/tipo-keyword -- una forma sin qualifier nunca
        # llegaria ahi (bug encontrado en revision de calidad). Los alias de
        # import NO son parte del sistema de hooks, asi que este lookahead
        # sigue exigiendo IDENTIFIER (no DUNDER) para el nombre del alias.
        if _looks_like_import_binding(cursor):
            return _parse_import_binding(cursor, ctx, tok, qualifier=None)
        if _looks_like_typed_decl(cursor):
            return parse_var_decl(cursor, ctx)
        return parse_expr_stmt(cursor, ctx)

    handler = _STATEMENT_DISPATCH.get(tok.type)
    if handler is not None:
        return handler(cursor, ctx)
    return parse_expr_stmt(cursor, ctx)


def _looks_like_typed_decl(cursor: Cursor) -> bool:
    """¿El nombre nominal en curso (IDENTIFIER o DUNDER) arranca un 'type'
    (var_decl) en vez de una expresion? Se cumple si, saltando la cadena
    cualificada (``.``) y los sufijos de tipo (``?`` y ``ptr [mutable]``),
    aparece OTRO nombre. Es lookahead puro: no consume tokens ni reparsea.

    La cadena cualificada es lo que distingue ``dt.int8 x;`` (declaracion de
    una variable de un tipo de libreria) de ``dt.int8;`` o ``a.b = c;``
    (expresiones). Los sufijos cubren ``String ptr s;`` / ``Nodo? n;``: sin
    saltarlos, un declarador de puntero se tomaria por una expresion (``ptr``
    es keyword, no operador, asi que solo puede estar formando un tipo aqui).
    """
    offset = 1
    while (cursor.peek(offset).type is TokenType.DOT
           and _is_name(cursor.peek(offset + 1).type)):
        offset += 2
    while True:
        t = cursor.peek(offset).type
        if t is TokenType.NULLABLE:
            offset += 1
        elif t is TokenType.POINTER:
            offset += 1
            if cursor.peek(offset).type is TokenType.MUTABLE:
                offset += 1
        else:
            break
    return _is_name(cursor.peek(offset).type)


def _is_name(tok_type: TokenType) -> bool:
    return tok_type is TokenType.IDENTIFIER or tok_type is TokenType.DUNDER


def parse_var_decl(cursor: Cursor, ctx: ParserContext) -> ast.Statement:
    """``[qualifier] type IDENTIFIER [ "=" expression ] ";"``.

    Caso especial (no cubierto por el EBNF formal, ver ``ast_nodes.ImportBinding``):
    ``[qualifier] IDENTIFIER "=" ( "#import" | "#from" ) ...`` -- el patron
    real de TODOS los ejemplos del lenguaje (``const IO = #import IO;``), sin
    anotacion de tipo. Se detecta con lookahead puro (``IDENTIFIER ASSIGN
    DIRECTIVE``) antes de intentar ``parse_type``.
    """
    start_tok = cursor.peek()
    qualifier = None
    if cursor.check(TokenType.CONST):
        qualifier = "const"
        cursor.advance()
    elif cursor.check(TokenType.VAR):
        qualifier = "var"
        cursor.advance()

    if _looks_like_import_binding(cursor):
        return _parse_import_binding(cursor, ctx, start_tok, qualifier)

    # 'const type int8;' declara un TIPO, no una variable: el token 'type'
    # tras el qualifier desvia a type_decl (ver parse_type_decl).
    if cursor.check(TokenType.TYPE):
        return parse_type_decl(cursor, ctx, start_tok, qualifier)

    type_expr = parse_type(cursor, ctx)
    # 'const a = ...': lo que se leyo como TIPO era en realidad el nombre, y
    # falta la anotacion. Sin este caso el error hablaba de un nombre que
    # falta ("se esperaba IDENTIFIER, se encontro ASSIGN") justo despues de
    # haberse comido el nombre que si estaba — el diagnostico apuntaba al
    # sintoma y no a la causa.
    if cursor.check(TokenType.ASSIGN) and isinstance(
            type_expr, ast.NominalTypeExpr):
        raise ParseError.MissingTypeAnnotationError(
            f"falta el tipo de '{type_expr.name}': en suriaX un binding se "
            f"anota siempre. Escribe '{qualifier or 'var'} <tipo> "
            f"{type_expr.name} = ...' (no hay inferencia de tipos: el tipo de "
            "una variable se lee sin ejecutar el compilador en la cabeza)",
            line=type_expr.ln, column=type_expr.col,
        )
    name_tok = cursor.expect_name()

    value = None
    if cursor.match(TokenType.ASSIGN):
        value = pratt.parse_expression(cursor, ctx)

    cursor.expect(TokenType.SEMICOLON)
    return ast.VarDecl(ln=start_tok.ln, col=start_tok.col, qualifier=qualifier,
                        type=type_expr, name=name_tok.lexeme, value=value)


def parse_type_decl(cursor: Cursor, ctx: ParserContext, start_tok=None,
                    qualifier=None) -> ast.TypeDecl:
    """``[qualifier] "type" IDENTIFIER [ "=" expression ] ";"`` (EBNF secc. 4).

    Declara un tipo nominal OPACO (ver ``ast_nodes.TypeDecl``). Se alcanza
    por dos vias: desde ``parse_var_decl`` cuando hay qualifier
    (``const type int8;``) y desde el dispatch cuando no lo hay
    (``type Blk;``); por eso ``start_tok``/``qualifier`` son opcionales.
    """
    if start_tok is None:
        start_tok = cursor.peek()
    cursor.expect(TokenType.TYPE)
    name_tok = cursor.expect_name()
    params = parse_type_params(cursor, ctx)

    value = None
    if cursor.match(TokenType.ASSIGN):
        # 'type' es de primera clase: el valor es una expresion que produce
        # un tipo (p. ej. una llamada a una 'fn ... -> type').
        value = pratt.parse_expression(cursor, ctx)

    cursor.expect(TokenType.SEMICOLON)
    return ast.TypeDecl(ln=start_tok.ln, col=start_tok.col,
                        qualifier=qualifier, name=name_tok.lexeme, value=value,
                        type_params=params)


def _looks_like_import_binding(cursor: Cursor) -> bool:
    return (
        cursor.peek().type is TokenType.IDENTIFIER
        and cursor.peek(1).type is TokenType.ASSIGN
        and cursor.peek(2).type is TokenType.DIRECTIVE
        and cursor.peek(2).value in ("import", "from")
    )


def _parse_import_binding(cursor: Cursor, ctx: ParserContext, start_tok, qualifier) -> ast.ImportBinding:
    name_tok = cursor.expect(TokenType.IDENTIFIER)
    cursor.expect(TokenType.ASSIGN)
    directive_name = cursor.peek().value
    source = parse_import_dir(cursor, ctx) if directive_name == "import" else parse_from_dir(cursor, ctx)
    return ast.ImportBinding(ln=start_tok.ln, col=start_tok.col, qualifier=qualifier,
                              name=name_tok.lexeme, source=source)


#: '++' / '--' -> el operador binario que los expande.
_PASO = {TokenType.INCREMENT: "+", TokenType.DECREMENT: "-"}


def parse_expr_stmt(cursor: Cursor, ctx: ParserContext) -> ast.ExprStmt:
    tok = cursor.peek()
    expr = pratt.parse_expression(cursor, ctx)
    # 'x++;' / 'x--;'. Son SENTENCIA, no expresion: como expresion habria que
    # decidir si valen el valor viejo o el nuevo, y esa distincion (i++ vs ++i)
    # es una fuente de bugs que no compra nada — aqui el valor se descarta.
    paso = _PASO.get(cursor.peek().type)
    if paso is not None:
        op_tok = cursor.advance()
        from ..expressions.led import expandir_compuesta
        uno = ast.Literal(ln=op_tok.ln, col=op_tok.col, value=1,
                          literal_kind="int")
        expr = expandir_compuesta(op_tok, expr, uno, paso)
    cursor.expect(TokenType.SEMICOLON)
    return ast.ExprStmt(ln=tok.ln, col=tok.col, expr=expr)


def _parse_mutable_misuse(cursor: Cursor, ctx: ParserContext) -> ast.Statement:
    """'mutable' arrancando un statement: siempre es el mal uso historico como
    qualifier de variable. Era valido como modificador de region
    ('mutable region r'), pero las regiones se retiraron en v0.2.0; hoy
    'mutable' solo califica punteros ('ptr mutable T'). Error dirigido con la
    migracion."""
    tok = cursor.peek()
    raise ParseError.ExpectedTokenError(
        "'mutable' ya no califica variables: usa 'var' para un binding "
        "mutable ('var int x = 10;'); 'mutable' aplica a punteros "
        "('T ptr mutable') y a regiones ('mutable region r')",
        line=tok.ln, column=tok.col,
    )


def _parse_visibility_misuse(cursor: Cursor, ctx: ParserContext) -> ast.Statement:
    """'public'/'private'/'internal' dentro de un bloque: solo son validas
    como prefijo de una declaracion de nivel superior."""
    tok = cursor.peek()
    raise ParseError.InvalidStatementError(
        "la visibilidad (public/private/internal) solo aplica a declaraciones "
        "de nivel superior, no dentro de un bloque",
        line=tok.ln, column=tok.col,
    )


def _parse_specifier_misuse(cursor: Cursor, ctx: ParserContext) -> ast.Statement:
    """'hook'/'dunder' fuera de una declaracion de funcion top-level."""
    tok = cursor.peek()
    raise ParseError.ExpectedTokenError(
        f"'{tok.lexeme}' solo puede preceder a 'fn' en una declaracion de "
        "nivel superior ('hook fn __free__(...)')",
        line=tok.ln, column=tok.col,
    )


def _parse_ptr_prefix_misuse(cursor: Cursor, ctx: ParserContext) -> ast.Statement:
    """'ptr' arrancando un statement: era la forma prefija, ya retirada."""
    tok = cursor.peek()
    raise ParseError.ExpectedTokenError(
        "'ptr' es un sufijo postfijo: el tipo va primero ('int ptr p = &x;', "
        "no 'ptr int p = &x;')",
        line=tok.ln, column=tok.col,
    )


_STATEMENT_DISPATCH: Dict[TokenType, Callable[[Cursor, ParserContext], ast.Statement]] = {
    TokenType.CONST: parse_var_decl,
    TokenType.VAR: parse_var_decl,
    TokenType.TYPE: parse_type_decl,  # 'type X;' sin qualifier
    TokenType.MUTABLE: _parse_mutable_misuse,  # mal uso historico como qualifier
    TokenType.VOID: parse_var_decl,
    TokenType.BOOL: parse_var_decl,
    TokenType.INT: parse_var_decl,
    TokenType.FLOAT: parse_var_decl,
    TokenType.CHAR: parse_var_decl,
    TokenType.STR: parse_var_decl,
    TokenType.ERRORTYPE: parse_var_decl,  # 'error int n = ...;' (tipo union)
    TokenType.THROW: parse_throw_stmt,
    TokenType.TRY: parse_try_stmt,
    TokenType.POINTER: _parse_ptr_prefix_misuse,  # 'ptr' ya no arranca un tipo (es postfijo)
    TokenType.IF: parse_if_stmt,
    TokenType.WHILE: parse_while_stmt,
    TokenType.MATCH: parse_match_stmt,
    TokenType.RETURN: parse_return_stmt,
    TokenType.BREAK: parse_break_stmt,
    TokenType.CONTINUE: parse_continue_stmt,
    TokenType.MOVE: parse_move_stmt,     # 'move expr;' o 'move region a -> region b;'
    TokenType.FREE: parse_free_stmt,
    # mal uso dentro de un bloque: visibilidad/especificador solo top-level
    TokenType.PUBLIC: _parse_visibility_misuse,
    TokenType.PRIVATE: _parse_visibility_misuse,
    TokenType.INTERNAL: _parse_visibility_misuse,
    TokenType.HOOK: _parse_specifier_misuse,
    TokenType.DUNDER_KW: _parse_specifier_misuse,
}


__all__ = ["parse_statement", "parse_var_decl", "parse_type_decl", "parse_expr_stmt"]
