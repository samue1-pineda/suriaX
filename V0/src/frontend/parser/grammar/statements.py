"""``statement`` dispatch + ``var_decl`` + ``type_decl`` + ``expr_stmt``
(EBNF).

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
from .testing import parse_expect_stmt
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


def _with(cursor: Cursor, ctx: ParserContext) -> ast.Statement:
    from .with_stmt import parse_with_stmt  # import diferido: with -> block -> statements
    return parse_with_stmt(cursor, ctx)


def _fn_statement(cursor: Cursor, ctx: ParserContext) -> ast.Statement:
    """``fn(int) -> int g = doble;``: un TIPO funcion arranca la declaracion.

    Igual que ``int x = 3;`` se escribe sin ``var``, un binding de tipo
    funcion tambien. ``fn`` seguido de ``(`` solo puede ser un tipo (una
    declaracion de funcion lleva su nombre ahi); cualquier otra forma sigue
    el camino de siempre, con el diagnostico de siempre."""
    if cursor.peek(1).type is TokenType.L_PAREN:
        return parse_var_decl(cursor, ctx)
    return parse_expr_stmt(cursor, ctx)


#: tokens que solo pueden empezar un TIPO, nunca una expresion: tras un '('
#: al comienzo de una sentencia dicen que el parentesis agrupa un tipo
_TYPE_ONLY_STARTS = frozenset({
    TokenType.VOID, TokenType.BOOL, TokenType.INT, TokenType.FLOAT,
    TokenType.CHAR, TokenType.STR, TokenType.BYTE, TokenType.ERRORTYPE,
})


def _paren_statement(cursor: Cursor, ctx: ParserContext) -> ast.Statement:
    """``(fn(int) -> int)? h = null;``: un tipo ENTRE PARENTESIS arranca la
    declaracion, igual que ``fn(int) -> int g = doble;`` sin ``var``.

    Se decide con dos tokens de lookahead y sin retroceso: tras el ``(``,
    ``fn (`` o una palabra de tipo (``int``, ``str``, ``error``...) no pueden
    empezar ninguna expresion, asi que el parentesis solo puede agrupar un
    tipo. Un nombre (``(Caja ptr)? p``) si podria empezar una expresion
    (``(c) = d;``): ese caso sigue el camino de las expresiones y, si como
    expresion no se entiende y tiene forma de tipo, el error pide ``var``.
    Antes la forma con ``fn`` era ``PAR012: token inesperado en expresion:
    FUNCTION``, que no decia que faltaba ``var``."""
    nxt = cursor.peek(1).type
    if (nxt is TokenType.FUNCTION and cursor.peek(2).type is TokenType.L_PAREN)             or nxt in _TYPE_ONLY_STARTS:
        return parse_var_decl(cursor, ctx)
    start = cursor.pos
    try:
        return parse_expr_stmt(cursor, ctx)
    except ParseError.ParseError as exc:
        if not _parenthesized_type_ahead(cursor, start):
            raise
        raise ParseError.ExpectedTokenError(
            f"{exc.message}. Si es una declaracion con un tipo entre "
            "parentesis, empiezala con 'var' o 'const' "
            "('var (Caja ptr)? p = null;'): sin ellos, un '(' al comienzo de "
            "una sentencia abre una expresion",
            line=exc.line, column=exc.column,
        ) from exc


def _parenthesized_type_ahead(cursor: Cursor, start: int) -> bool:
    """¿Tras el ``(`` de ``start`` y su ``)`` viene un sufijo de tipo (``?``
    o ``ptr``) seguido de un nombre? Es la forma ``(T ptr)? nombre``, que
    ninguna expresion tiene. Solo se mira para EXPLICAR un error: no decide
    como se lee la sentencia."""
    tokens, i, depth = cursor.tokens, start, 0
    while i < len(tokens):
        t = tokens[i].type
        if t is TokenType.L_PAREN:
            depth += 1
        elif t is TokenType.R_PAREN:
            depth -= 1
            if depth == 0:
                break
        elif t in (TokenType.SEMICOLON, TokenType.L_BRACE, TokenType.R_BRACE,
                   TokenType.EOF):
            return False
        i += 1
    i += 1
    seen_suffix = False
    while i < len(tokens) and tokens[i].type in (TokenType.NULLABLE,
                                                 TokenType.POINTER,
                                                 TokenType.MUTABLE):
        seen_suffix = True
        i += 1
    return seen_suffix and i < len(tokens) and _is_name(tokens[i].type)


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
    if isinstance(type_expr, ast.FunctionTypeExpr) and qualifier is None \
            and cursor.peek().type in (TokenType.L_BRACE, TokenType.SEMICOLON):
        # 'fn () -> int { ... }': se leyo un TIPO funcion porque falta el
        # nombre de la funcion, no el de una variable
        nxt = cursor.peek()
        raise ParseError.ExpectedTokenError(
            "a la declaracion de la funcion le falta el NOMBRE "
            "('fn nombre() -> ...'); 'fn(...)' sin nombre es un TIPO funcion",
            line=nxt.ln, column=nxt.col,
        )
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
    # 'int vec.Vector val[8];' -- declaracion de CONTENEDOR: lo que se leyo
    # como tipo era el ELEMENTO y lo que sigue es el contenedor.
    contenedor = _contenedor_tras_elemento(cursor, ctx)
    name_tok = cursor.expect_name()

    capacidad = None
    if cursor.check(TokenType.L_BRACKET):
        cursor.advance()
        capacidad = pratt.parse_expression(cursor, ctx)
        cursor.expect(TokenType.R_BRACKET)

    value = None
    if cursor.match(TokenType.ASSIGN):
        value = pratt.parse_expression(cursor, ctx)

    cursor.expect(TokenType.SEMICOLON)

    if contenedor is not None or capacidad is not None:
        return _decl_de_contenedor(start_tok, qualifier, type_expr, contenedor,
                                    name_tok, capacidad, value)
    return ast.VarDecl(ln=start_tok.ln, col=start_tok.col, qualifier=qualifier,
                        type=type_expr, name=name_tok.lexeme, value=value)


def _contenedor_tras_elemento(cursor: Cursor, ctx: ParserContext):
    """El CONTENEDOR de ``int vec.Vector val[8];``, o ``None``.

    Una declaracion corriente tiene un solo tipo (``int val``); la de un
    contenedor tiene dos (``int vec.Vector val``). Se distinguen mirando: si
    tras el primer tipo viene algo que TAMBIEN parsea como tipo y despues un
    nombre, era la forma de contenedor. Si no, el cursor vuelve exactamente
    donde estaba.

    El retroceso esta acotado —nunca cruza el nombre— y no registra errores
    en ``ctx``, igual que el de los argumentos de tipo de un generico
    (``expressions/nud._type_args_de_generico``), que es el otro sitio del
    parser donde una forma se decide mirando y no adivinando.
    """
    if not cursor.check(TokenType.IDENTIFIER):
        return None
    inicio = cursor.pos
    try:
        contenedor = parse_type(cursor, ctx)
    except ParseError.ParseError:
        cursor.pos = inicio
        return None
    if cursor.peek().type in (TokenType.IDENTIFIER, TokenType.DUNDER):
        return contenedor
    if cursor.check(TokenType.L_BRACKET):
        # 'int vec.Vector[10];' -- es la forma de CONTENEDOR sin su nombre.
        # Sin este caso el retroceso tomaba 'vec' por el nombre y el error
        # salia en el '.' ("se esperaba SEMICOLON, se encontro DOT"), que
        # apunta al sintoma y no a lo que falta.
        raise ParseError.MissingTypeAnnotationError(
            f"falta el NOMBRE de la variable: '{_texto_de_tipo(contenedor)}' "
            f"es el contenedor y '[...]' su capacidad, pero no dice como se "
            f"llama. Escribe '<tipo> {_texto_de_tipo(contenedor)} <nombre>[...]'",
            line=cursor.peek().ln, column=cursor.peek().col,
        )
    cursor.pos = inicio
    return None


def _decl_de_contenedor(start_tok, qualifier, elemento, contenedor, name_tok,
                        capacidad, value) -> ast.VarDecl:
    """``int vec.Vector val[8];`` -> el ``var`` y la llamada que ya existian.

    Es AZUCAR y se deshace aqui a proposito: la Semantica, el HIR, el
    interprete y los backends siguen viendo exactamente lo mismo que ven hoy
    para ``var vec.Vector<int> val = vec.make<int>(8);``. Una construccion
    nueva en el AST habria obligado a cada consumidor a aprenderla para no
    producir nada distinto.

    El CONSTRUCTOR es ``make`` en el modulo del contenedor: ``vec.Vector`` ->
    ``vec.make``. Es una convencion de la libreria, no del compilador — el
    mismo criterio que hace que ``print`` viva en ``IO`` y no en la gramatica.
    """
    ln, col = name_tok.ln, name_tok.col
    if contenedor is None:
        # 'int val[8];' sin contenedor: no hay a quien pedirle el espacio.
        raise ParseError.MissingTypeAnnotationError(
            f"'{name_tok.lexeme}[...]' reserva espacio, pero no dice EN QUE: "
            f"escribe el contenedor entre el tipo del elemento y el nombre "
            f"('{_texto_de_tipo(elemento)} vec.Vector {name_tok.lexeme}[...]')",
            line=ln, column=col)

    tipo = _instanciar(contenedor, elemento)
    if value is None:
        if capacidad is None:
            raise ParseError.MissingTypeAnnotationError(
                f"'{name_tok.lexeme}' declara un contenedor sin capacidad ni "
                f"valor: escribe cuantos espacios reserva "
                f"('{name_tok.lexeme}[8]') o inicializalo con '='",
                line=ln, column=col)
        value = _llamada_al_constructor(contenedor, elemento, capacidad, ln, col)
        azucar = (f"'{name_tok.lexeme}[...]': la reserva llama al constructor "
                  "de la libreria (make)")
    else:
        azucar = ""
    return ast.VarDecl(ln=start_tok.ln, col=start_tok.col, qualifier=qualifier,
                       type=tipo, name=name_tok.lexeme, value=value,
                       capacity=capacidad, azucar=azucar)


def _instanciar(contenedor, elemento):
    """``vec.Vector`` + ``int`` -> el ``TypeExpr`` de ``vec.Vector<int>``."""
    if not isinstance(contenedor, ast.NominalTypeExpr):
        raise ParseError.MissingTypeAnnotationError(
            "el contenedor de una declaracion con '[...]' tiene que ser un "
            "tipo con nombre ('vec.Vector'), no un puntero ni un nullable",
            line=contenedor.ln, column=contenedor.col)
    return ast.NominalTypeExpr(ln=contenedor.ln, col=contenedor.col,
                               name=contenedor.name, args=[elemento])


def _llamada_al_constructor(contenedor, elemento, capacidad, ln, col):
    """``vec.Vector`` -> la llamada ``vec.make<int>(n)``."""
    modulo, _, _hoja = contenedor.name.rpartition(".")
    callee: ast.Expression = ast.Identifier(ln=ln, col=col, name="make")
    if modulo:
        base: ast.Expression = ast.Identifier(ln=ln, col=col, name=modulo)
        callee = ast.MemberAccess(ln=ln, col=col, obj=base, member="make")
    return ast.Call(ln=ln, col=col, callee=callee, args=[capacidad],
                    type_args=[elemento])


def _texto_de_tipo(t) -> str:
    if isinstance(t, ast.NominalTypeExpr):
        return t.name
    if isinstance(t, ast.FunctionTypeExpr):
        return "fn(...)"
    return "<tipo>"


def parse_type_decl(cursor: Cursor, ctx: ParserContext, start_tok=None,
                    qualifier=None) -> ast.TypeDecl:
    """``[qualifier] "type" IDENTIFIER [ "=" expression ] ";"`` (EBNF).

    Declara un tipo nominal OPACO (ver ``ast_nodes.TypeDecl``). Se alcanza
    por dos vias: desde ``parse_var_decl`` cuando hay qualifier
    (``const type int8;``) y desde el dispatch cuando no lo hay
    (``type Blk;``); por eso ``start_tok``/``qualifier`` son opcionales.
    """
    if start_tok is None:
        start_tok = cursor.peek()
    cursor.expect(TokenType.TYPE)
    name_tok = cursor.expect_name()
    params, bounds = parse_type_params(cursor, ctx)

    value = None
    if cursor.match(TokenType.ASSIGN):
        # 'type' es de primera clase: el valor es una expresion que produce
        # un tipo (p. ej. una llamada a una 'fn ... -> type').
        value = pratt.parse_expression(cursor, ctx)

    cursor.expect(TokenType.SEMICOLON)
    return ast.TypeDecl(ln=start_tok.ln, col=start_tok.col,
                        qualifier=qualifier, name=name_tok.lexeme, value=value,
                        type_params=params, type_bounds=bounds)


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
    TokenType.WITH: lambda c, x: _with(c, x),
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
    TokenType.BYTE: parse_var_decl,
    TokenType.ERRORTYPE: parse_var_decl,  # 'error int n = ...;' (tipo union)
    TokenType.FUNCTION: _fn_statement,  # 'fn(int) -> int g = doble;'
    TokenType.L_PAREN: _paren_statement,  # '(fn(int) -> int)? h = null;'
    TokenType.THROW: parse_throw_stmt,
    TokenType.TRY: parse_try_stmt,
    TokenType.EXPECT: parse_expect_stmt,   # solo dentro de un 'test'
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
