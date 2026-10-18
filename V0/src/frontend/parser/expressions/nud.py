"""Handlers de la posicion PREFIJO de una expresion.

Implementa la cadena estructural completa
``unary -> postfix -> primary`` de ``docs/gramar/grammar.ebnf``. Estos niveles NO se resuelven por binding power (a diferencia de
los operadores binarios de ``precedence.py``): el EBNF los define como
niveles fijos anidados a la derecha, asi que se implementan como funciones
que se llaman entre si.

``PRIMARY_HANDLERS`` es la tabla de despacho ``TokenType -> constructor``
para la regla ``primary``: agregar una forma primaria nueva es agregar una
entrada aqui, sin tocar ``parse_unary``/``parse_postfix``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Dict, List, Union

try:
    from include import ast_nodes as ast
    from include.t_types import Interp, StringValue, Token, TokenType
    from error_handler import ParseError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from t_types import Interp, StringValue, Token, TokenType  # type: ignore
    import ParseError  # type: ignore

from ..context import ParserContext
from ..cursor import Cursor

# --- prefijos unarios: 'unary = ( "not" | "-" | "&" ) unary | placement' ---
# '&' construye su nodo propio (AddrOf): las reglas de punteros (lvalue,
# mutabilidad heredada) son semantica de ese nodo, no de un operador generico.
_UNARY_OPS: Dict[TokenType, str] = {
    TokenType.NOT: "not",
    TokenType.MINUS: "-",
    TokenType.TILDE: "~",
}


def parse_unary(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.peek()
    if tok.type is TokenType.ADDRESS:
        cursor.advance()
        operand = parse_unary(cursor, ctx)
        return ast.AddrOf(ln=tok.ln, col=tok.col, operand=operand)
    operator = _UNARY_OPS.get(tok.type)
    if operator is not None:
        cursor.advance()
        operand = parse_unary(cursor, ctx)  # right-recursivo: '- - x' es valido
        # '-' PEGADO a un literal numerico produce el literal NEGATIVO, no una
        # negacion de uno positivo. No es una optimizacion: es la unica forma
        # de escribir el minimo de 'int'. El rango de un entero con signo no
        # es simetrico —el minimo (-2^63) existe pero su opuesto (+2^63) NO—,
        # asi que leerlo como "menos el literal 9223372036854775808" obliga a
        # pasar por un valor que el tipo no puede representar.
        if operator == "-" and isinstance(operand, ast.Literal) \
                and operand.literal_kind in ("int", "float"):
            return ast.Literal(ln=tok.ln, col=tok.col, value=-operand.value,
                               literal_kind=operand.literal_kind)
        return ast.UnaryOp(ln=tok.ln, col=tok.col, operator=operator, operand=operand)
    return parse_postfix(cursor, ctx)


def parse_postfix(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    """``postfix = ( primary | struct_literal ) { "." IDENTIFIER | "(" [arg_list] ")" | "[" expression "]" }``."""
    expr = parse_primary(cursor, ctx)
    if expr.__class__ is ast.Lambda:
        # una lambda no lleva sufijos: 'lambda (...) -> int { ... }(3)' no es
        # una llamada a la lambda (solo vale como argumento), y en la forma
        # corta el sufijo ya lo consumio su cuerpo ('x.campo' es de 'x')
        return expr
    # 'dotted' acumula el nombre mientras la expresion siga siendo un NOMBRE
    # puro ('Nodo', 'point.Point'); pasa a None en cuanto aparece una llamada
    # o una indexacion, porque entonces ya no nombra un tipo.
    dotted = expr.name if expr.__class__ is ast.Identifier else None
    while True:
        tok = cursor.peek()
        # struct_literal = IDENTIFIER { "." IDENTIFIER } "{" [ field_init... ] "}"
        # solo tras un nombre NOMINAL, desnudo ('Nodo{ v: 1 }') o cualificado
        # por su modulo ('point.Point{ x: 1 }' — un struct publicado por una
        # libreria se nombra igual en una anotacion que en un literal). No hay
        # ambiguedad con bloques (las condiciones van entre parentesis, un
        # bloque es statement, nunca sigue a un nombre en posicion de expresion).
        if tok.type is TokenType.L_BRACE and dotted is not None \
                and not ctx.no_struct_literal:
            expr = _struct_literal(cursor, ctx, expr, dotted)
            dotted = None
        elif tok.type is TokenType.LESS and dotted is not None:
            # posible GENERICO: un literal ('Caja<int>{ v: 1 }'), una llamada
            # ('make<int>(4)') o la variante de un enum generico
            # ('Res<int, str>.Ok(5)'). Es la unica posicion del lenguaje donde
            # '<' es ambiguo (comparacion vs argumentos de tipo), y se
            # resuelve MIRANDO que hay tras el '>': una llave abre un literal,
            # un parentesis una llamada y un punto la variante. Cualquier otra
            # cosa y se retrocede: el '<' vuelve a ser el operador que siempre
            # fue. (Tras 'a < b >' un '.' solo podria empezar un '.campo' de
            # 'with', y comparar un 'bool' con '>' ya es un error de tipos.)
            permitidos = (TokenType.L_PAREN, TokenType.DOT) \
                if ctx.no_struct_literal \
                else (TokenType.L_BRACE, TokenType.L_PAREN, TokenType.DOT)
            type_args, seguido_de = _type_args_de_generico(cursor, ctx,
                                                           permitidos)
            if type_args is None:
                if seguido_de in _VALUE_END:
                    _generic_without_call(tok, dotted)
                return expr
            if seguido_de is TokenType.L_BRACE:
                expr = _struct_literal(cursor, ctx, expr, dotted, type_args)
            elif seguido_de is TokenType.DOT:
                # 'Res<int, str>.Ok': los argumentos son del ENUM que nombra
                # 'expr'; el '.' lo consume la vuelta siguiente
                expr.type_args = type_args
            else:
                cursor.advance()          # el '('
                args, inner_hint = _parse_call_args(cursor, ctx)
                cursor.expect(TokenType.R_PAREN)
                expr = ast.Call(ln=expr.ln, col=expr.col, callee=expr,
                                args=args, type_args=type_args)
                hint = _comparison_reading(ctx, dotted, type_args)
                if hint:
                    ctx.args_hint = hint      # tambien para la llamada de fuera
                expr.ambiguity_hint = hint or inner_hint
            dotted = None
        elif tok.type is TokenType.DOT:
            cursor.advance()
            member_tok = cursor.expect_name()
            expr = ast.MemberAccess(ln=expr.ln, col=expr.col, obj=expr, member=member_tok.lexeme)
            if dotted is not None:
                dotted = f"{dotted}.{member_tok.lexeme}"
        elif tok.type is TokenType.L_PAREN:
            cursor.advance()
            args, inner_hint = _parse_call_args(cursor, ctx)
            cursor.expect(TokenType.R_PAREN)
            expr = ast.Call(ln=expr.ln, col=expr.col, callee=expr, args=args,
                            ambiguity_hint=inner_hint)
            dotted = None
        elif tok.type is TokenType.L_BRACKET:
            cursor.advance()
            from .. import pratt  # import diferido: 'pratt' importa este modulo
            with _struct_literals_allowed(ctx):
                index_expr = pratt.parse_expression(cursor, ctx)
            cursor.expect(TokenType.R_BRACKET)
            expr = ast.Index(ln=expr.ln, col=expr.col, obj=expr, index=index_expr)
            dotted = None
        else:
            return expr


def _type_args_de_generico(cursor: Cursor, ctx: ParserContext, permitidos):
    """``"<" type { "," type } ">"`` SI y solo si le sigue uno de ``permitidos``.

    Devuelve ``(argumentos, token que sigue)``, o ``(None, X)`` si lo que
    hay no es esa forma (``X`` es el token tras el ``>`` si los tipos se
    leyeron, ``None`` si ni eso) — en cuyo caso el cursor queda EXACTAMENTE donde
    estaba y el ``<`` lo recoge el motor Pratt como comparacion. Es el unico
    retroceso del parser, y esta acotado: nunca cruza el ``>``, y ningun
    error llega a ``ctx`` porque ``parse_type_args`` senala lanzando, no
    registrando.

    ``permitidos`` es lo que separa ``Caja<int>{...}`` (literal) de
    ``make<int>(...)`` (llamada). Dentro de la condicion de un ``if`` no se
    admite el literal (``ctx.no_struct_literal``), pero la LLAMADA si: no
    puede confundirse con el cuerpo del ``if`` porque termina en ``)``.
    """
    inicio = cursor.pos
    from ..grammar.types import parse_type_args
    try:
        args = parse_type_args(cursor, ctx)
    except ParseError.ParseError:
        cursor.pos = inicio
        return None, None
    siguiente = cursor.peek().type
    if siguiente not in permitidos:
        # se devuelve QUE seguia: tras 'nombre<tipos>' un fin de valor
        # ('maximo<int>;') es un generico sin llamar, no una comparacion
        cursor.pos = inicio
        return None, siguiente
    return args, siguiente


#: lo que puede seguir a un VALOR completo (fin de sentencia, de argumento o
#: de agrupacion). Tras 'nombre<tipos>' ninguna comparacion termina asi —a
#: 'a < b >' le falta un operando—, asi que ahi solo cabe un generico.
_VALUE_END = (TokenType.SEMICOLON, TokenType.COMMA, TokenType.R_PAREN)


def _generic_without_call(less, name: str) -> None:
    """``maximo<int>`` sin llamarlo: una funcion GENERICA usada como valor.

    Las funciones son valores, pero una generica todavia no: haria falta que
    el HIR lleve la instancia (con que tipos se usa) para que un backend que
    monomorfiza sepa que copia bajar, y eso no se decidio. Se rechaza aqui,
    donde se ve la forma, con lo que hay que escribir; sin esto el error
    salia sobre el '>' hablando de una comparacion que nadie escribio."""
    raise ParseError.InvalidExpressionError(
        f"'{name}<...>' sin llamar: una funcion GENERICA todavia no se "
        "puede usar como valor. Envuelvela en una funcion con los tipos "
        "escritos (fn maximo_int(int a, int b) -> int { return "
        "maximo<int>(a, b); }) y usa esa",
        line=less.ln, column=less.col,
    )


def _struct_literal(cursor: Cursor, ctx: ParserContext,
                    name_expr: ast.Expression, type_name: str,
                    type_args=None) -> ast.Expression:
    """``IDENTIFIER { "." IDENTIFIER } [ type_args ] "{" [ IDENTIFIER ":" expression { "," ... } ] "}"``.

    Instancia un struct nominal (``type_name`` es el tipo, ya sea desnudo o
    cualificado por su modulo). Coma final tolerada; campos en el orden
    escrito."""
    cursor.expect(TokenType.L_BRACE)
    from .. import pratt
    names: List[str] = []
    values: List[ast.Expression] = []
    with _struct_literals_allowed(ctx):
        while not cursor.check(TokenType.R_BRACE) and not cursor.at_end():
            name_tok = cursor.expect_name()
            cursor.expect(TokenType.COLON)
            names.append(name_tok.lexeme)
            values.append(pratt.parse_expression(cursor, ctx))
            if not cursor.match(TokenType.COMMA):
                break
    cursor.expect(TokenType.R_BRACE)
    return ast.StructLiteral(ln=name_expr.ln, col=name_expr.col,
                             type_name=type_name, field_names=names,
                             values=values, type_args=type_args or [])


def _comparison_reading(ctx: ParserContext, name: str, type_args) -> str:
    """La explicacion de ``a<b, c>(d)`` cuando tambien eran dos comparaciones.

    Solo entre los argumentos de una llamada (``dos(a < b, c > (d))``), con
    dos o mas argumentos de tipo y todos nombres a secas: es la unica forma
    en que la coma puede separar dos comparaciones. La lectura GENERICA se
    mantiene (decision del mantenedor); esto solo se pega al error que
    produzca, para que diga por que se leyo asi y como escribir la otra."""
    if not ctx.in_call_args or len(type_args) < 2:
        return ""
    names = []
    for t in type_args:
        if not isinstance(t, ast.NominalTypeExpr) or t.args:
            return ""
        names.append(t.name)
    return (f"ojo: '{name}<{', '.join(names)}>(...)' se leyo como una llamada "
            f"GENERICA a '{name}' con los tipos {', '.join(names)}; entre los "
            "argumentos de una llamada, 'a < b, c > (d)' se lee asi. Si eran "
            f"comparaciones, ponlas entre parentesis: '({name} < {names[0]})'")


@contextmanager
def _struct_literals_allowed(ctx: ParserContext, in_args: bool = False):
    """Dentro de un DELIMITADOR (``(...)``, ``[...]``, ``{campo: ...}``) un
    literal de struct vuelve a ser valido aunque el contexto exterior lo
    haya suprimido: en ``case f(Nodo{ v: 1 })`` el '{' del argumento no es
    el cuerpo de la rama. Sin esto, la marca de ``ctx.no_struct_literal``
    se filtraria hacia dentro de las subexpresiones."""
    previous = ctx.no_struct_literal
    previous_args = ctx.in_call_args
    ctx.no_struct_literal = False
    # tambien marca si este delimitador es la lista de argumentos de una
    # llamada (ver _comparison_reading): dentro de '(...)' o '[...]' no
    ctx.in_call_args = in_args
    try:
        yield
    finally:
        ctx.no_struct_literal = previous
        ctx.in_call_args = previous_args


def _parse_call_args(cursor: Cursor, ctx: ParserContext):
    """Los argumentos de una llamada y la explicacion de una lectura generica
    ambigua entre ellos (``""`` si no la hubo; ver _comparison_reading)."""
    outer = ctx.args_hint
    ctx.args_hint = ""
    try:
        args = _parse_arg_list(cursor, ctx)
        return args, ctx.args_hint
    finally:
        ctx.args_hint = outer


def _parse_arg_list(cursor: Cursor, ctx: ParserContext) -> List[ast.Expression]:
    """``arg_list = expression { "," expression }``."""
    args: List[ast.Expression] = []
    if cursor.check(TokenType.R_PAREN):
        return args
    from .. import pratt
    with _struct_literals_allowed(ctx, in_args=True):
        args.append(pratt.parse_expression(cursor, ctx))
        while cursor.match(TokenType.COMMA):
            args.append(pratt.parse_expression(cursor, ctx))
    return args


def parse_primary(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.peek()
    handler = PRIMARY_HANDLERS.get(tok.type)
    if handler is None:
        raise ParseError.InvalidExpressionError(
            f"token inesperado en expresion: {tok.type.name}",
            line=tok.ln, column=tok.col,
        )
    return handler(cursor, ctx)


# ----------------------------------------------------------------------------
# handlers 'primary' individuales
# ----------------------------------------------------------------------------

def _miembro_del_receptor(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    from ..grammar.with_stmt import parse_receiver_member  # import diferido (ciclo)
    return parse_receiver_member(cursor, ctx)


def _identifier(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.advance()
    return ast.Identifier(ln=tok.ln, col=tok.col, name=tok.lexeme)


def _lit_int(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.advance()
    return ast.Literal(ln=tok.ln, col=tok.col, value=tok.value, literal_kind="int")


def _lit_float(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.advance()
    return ast.Literal(ln=tok.ln, col=tok.col, value=tok.value, literal_kind="float")


def _lit_char(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.advance()
    return ast.Literal(ln=tok.ln, col=tok.col, value=tok.value, literal_kind="char")


def _lit_true(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.advance()
    return ast.Literal(ln=tok.ln, col=tok.col, value=True, literal_kind="bool")


def _lit_false(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.advance()
    return ast.Literal(ln=tok.ln, col=tok.col, value=False, literal_kind="bool")


def _lit_null(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.advance()
    return ast.Literal(ln=tok.ln, col=tok.col, value=None, literal_kind="null")


def _lit_string(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    """Camino rapido sin interpolacion -> ``Literal``; con interpolacion ->
    ``InterpolatedString`` con cada ``{expr}`` ya analizado (ver ``_parse_interp``)."""
    tok = cursor.advance()
    sv: StringValue = tok.value
    if not sv.is_interpolated:
        return ast.Literal(ln=tok.ln, col=tok.col, value=sv.flat(), literal_kind="str")

    parts: List[Union[str, ast.Expression]] = []
    for part in sv.parts:
        parts.append(part if isinstance(part, str) else _parse_interp(part, tok, ctx))
    return ast.InterpolatedString(ln=tok.ln, col=tok.col, parts=parts)


def _parse_interp(interp: Interp, string_tok: Token,
                  ctx: ParserContext) -> ast.Expression:
    """Analiza el texto crudo de un ``{expr}`` como una expresion completa.

    El lexer solo delimita el texto de la interpolacion (ver ``Interp`` en
    ``t_types.py``); su analisis es responsabilidad del parser (EBNF).
    Se re-tokeniza y re-parsea el fragmento de forma aislada (una interpolacion
    nunca cruza saltos de linea, ver ``scanners/strings.py``). Los TOKENS del
    fragmento se llevan a su posicion real antes de parsearlos
    (:func:`_shift_tokens`), asi que cada nodo nace en su sitio: en
    ``f"{doble(mas_uno(3))}"`` cada llamada tiene su columna, y un error
    dentro de una interpolacion apunta a donde esta.
    """
    from src.frontend.lexer.lexer import Lexer as _Lexer

    # la linea de ESTA interpolacion: dos literales adyacentes en lineas
    # distintas son un solo token, con la linea del primero
    ln = interp.ln or string_tok.ln
    col = interp.col

    texto, conversion, formato = separar_formato(interp.expr)
    if formato is not None and not formato_valido(formato):
        raise ParseError.InvalidExpressionError(
            f"interpolacion invalida: el formato ':{formato}' no se entiende; "
            "es [0][ancho][.precision][tipo], con tipo d, x, X, b, o o f",
            line=ln, column=col,
        )
    sub_lexer = _Lexer(texto)
    sub_tokens = sub_lexer.tokenize()
    if sub_lexer.errors:
        # sin esto el error lexico se perdia y quedaba un 'token inesperado
        # en expresion: ERROR' que no decia que paso
        first = sub_lexer.errors[0]
        raise ParseError.InvalidExpressionError(
            f"interpolacion invalida: {first.message}",
            line=ln, column=col + (first.column or 1) - 1,
        )
    _shift_tokens(sub_tokens, ln, col)
    sub_cursor = Cursor(sub_tokens)
    sub_ctx = ParserContext()
    # '{.campo}' dentro de un 'with' se refiere a su receptor
    sub_ctx.with_receivers = list(ctx.with_receivers)

    from .. import pratt
    try:
        expr = pratt.parse_expression(sub_cursor, sub_ctx)
    except ParseError.ParseError as exc:
        raise ParseError.InvalidExpressionError(
            f"interpolacion invalida: {exc.message}",
            line=exc.line, column=exc.column,
        ) from exc
    if not sub_cursor.at_end():
        extra = sub_cursor.peek()
        raise ParseError.InvalidExpressionError(
            "la interpolacion contiene mas de una expresion",
            line=extra.ln, column=extra.col,
        )

    if conversion or formato:
        return ast.FormattedValue(ln=ln, col=col, value=expr,
                                  conversion=conversion, format_spec=formato or "")
    return expr


def _shift_tokens(tokens: List[Token], ln: int, col: int) -> None:
    """Lleva los tokens de un fragmento a su posicion en el archivo.

    El mini-lex de una interpolacion cuenta desde 1:1 y no cruza lineas: un
    token en la columna ``c`` del fragmento esta en la ``col + c - 1`` de la
    linea ``ln``. Se desplazan los TOKENS y no los nodos ya construidos (lo
    que se hacia antes, poniendolos TODOS en la posicion de la
    interpolacion): asi lo que el parser copia de fuera del fragmento —el
    receptor de un ``with`` en ``{.campo}``— conserva su posicion, y una
    f-string anidada recibe tambien la suya en sus interpolaciones."""
    for tok in tokens:
        tok.ln = ln + tok.ln - 1
        tok.col = col + tok.col - 1
        value = tok.value
        if tok.type is TokenType.STRING_LIT and value.is_interpolated:
            tok.value = StringValue(tuple(
                Interp(p.expr, col + p.col - 1, ln + (p.ln or 1) - 1)
                if isinstance(p, Interp) else p
                for p in value.parts))


def separar_formato(texto: str):
    """``'x!r:>8'`` -> ``('x', 'r', '>8')``; ``'n:08b'`` -> ``('n', '', '08b')``.

    El ``!`` y el ``:`` se buscan FUERA de parentesis, llaves, corchetes y
    literales: dentro de una interpolacion puede haber un literal de struct
    (``g{k: 1}``), una cadena con dos puntos o un ``!=``. El formato es
    ``None`` si no hay ``:``.
    """
    profundidad = 0
    i, n = 0, len(texto)
    while i < n:
        c = texto[i]
        if c in "\"'":
            i += 1
            while i < n and texto[i] != c:
                i += 2 if texto[i] == "\\" else 1
            i += 1
            continue
        if c in "([{":
            profundidad += 1
        elif c in ")]}":
            profundidad -= 1
        elif profundidad == 0 and c == "!" and texto[i + 1:i + 2] == "r" \
                and (i + 2 == n or texto[i + 2] == ":"):
            return texto[:i], "r", (texto[i + 3:] if i + 2 < n else None)
        elif profundidad == 0 and c == ":":
            return texto[:i], "", texto[i + 1:]
        i += 1
    return texto, "", None


#: ``[0][ancho][.precision][tipo]`` de un ``{x:spec}``. Una sola fuente: la
#: usa el parser y la publica ``--emit-lang-info`` (para colorearla).
FORMAT_SPEC = r"0?([1-9][0-9]*)?(\.[0-9]+)?[dxXbof]?"


def formato_valido(formato: str) -> bool:
    """``[0][ancho][.precision][tipo]``: la sintaxis. Que el tipo del valor
    admita ese formato lo decide la Semantica."""
    import re
    return re.fullmatch(FORMAT_SPEC, formato) is not None


def _grouping(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    """``"(" expression ")"`` -- no genera nodo propio, devuelve la interna."""
    cursor.expect(TokenType.L_PAREN)
    from .. import pratt
    with _struct_literals_allowed(ctx):
        expr = pratt.parse_expression(cursor, ctx)
    cursor.expect(TokenType.R_PAREN)
    return expr


def _sizeof(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    tok = cursor.expect(TokenType.SIZEOF)
    cursor.expect(TokenType.L_PAREN)
    from ..grammar.types import parse_type
    type_expr = parse_type(cursor, ctx)
    cursor.expect(TokenType.R_PAREN)
    return ast.SizeofExpr(ln=tok.ln, col=tok.col, type=type_expr)


def _move(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    """``"move" expression`` en posicion de expresion.

    La forma de SENTENCIA (``move x;``) la parsea 'grammar/memory.py', que
    mira el token antes de llegar aqui: las dos conviven porque significan
    cosas distintas — la sentencia invalida, la expresion ademas entrega el
    valor a quien la escribio.
    """
    tok = cursor.expect(TokenType.MOVE)
    operand = parse_unary(cursor, ctx)
    return ast.MoveExpr(ln=tok.ln, col=tok.col, operand=operand)


def _cast(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    """``"cast" type_args "(" expression ")"`` -- exactamente UN argumento de
    tipo (``cast<int8>(x)``); la posicion ``<...>`` es la regla compartida
    ``grammar/types.parse_type_args`` (los genericos de libreria la reusaran)."""
    tok = cursor.expect(TokenType.CAST)
    from ..grammar.types import parse_type_args
    type_args = parse_type_args(cursor, ctx)
    if len(type_args) != 1:
        raise ParseError.InvalidExpressionError(
            f"'cast' toma exactamente un argumento de tipo, recibe {len(type_args)}",
            line=tok.ln, column=tok.col,
        )
    cursor.expect(TokenType.L_PAREN)
    from .. import pratt
    value = pratt.parse_expression(cursor, ctx)
    cursor.expect(TokenType.R_PAREN)
    return ast.CastExpr(ln=tok.ln, col=tok.col, type=type_args[0], value=value)


def _lambda(cursor: Cursor, ctx: ParserContext) -> ast.Expression:
    """``"lambda" "(" [ param_list ] ")" "->" type ( ":" expression | block )``.

    Los tipos se escriben SIEMPRE, el de retorno incluido (``-> void`` si no
    devuelve nada): no hay inferencia, y una lambda no tiene una declaracion
    aparte donde leerlos.

    Que solo valga como ARGUMENTO de una llamada lo decide la Semantica (y
    lo explica): aqui se lee en cualquier posicion de expresion, para que el
    error diga por que no vale ahi y no "token inesperado".

    El cuerpo es una funcion: sus ``break``/``continue`` no salen a un bucle
    de fuera (no lo hay dentro de la lambda), un ``return`` devuelve de la
    lambda (tambien dentro de un ``finally`` de fuera) y ``expect`` no vale
    (es de un ``test``, no de una funcion). Por eso se lee con el contexto de
    bucles, ``finally`` y pruebas a cero, como el de una ``fn``.

    La forma CORTA es azucar: ``: e`` es ``{ return e; }`` (o ``{ e; }`` con
    retorno ``void``). Se marca en ``Lambda.short``."""
    tok = cursor.expect(TokenType.LAMBDA)
    from ..grammar.functions import parse_lambda_signature
    params, return_type = parse_lambda_signature(cursor, ctx, tok)
    saved = (ctx.loop_depth, ctx.finally_loops, ctx.in_test, ctx.expects,
             ctx.lambda_hides_loop, ctx.lambda_hides_test)
    ctx.lambda_hides_loop = ctx.lambda_hides_loop or ctx.loop_depth > 0
    ctx.lambda_hides_test = ctx.lambda_hides_test or ctx.in_test
    ctx.loop_depth, ctx.finally_loops, ctx.in_test = 0, [], False
    try:
        if cursor.match(TokenType.COLON):
            from .. import pratt
            with _struct_literals_allowed(ctx):
                value = pratt.parse_expression(cursor, ctx)
            if isinstance(return_type, ast.PrimitiveTypeExpr) \
                    and return_type.name == "void":
                only: ast.Statement = ast.ExprStmt(ln=value.ln, col=value.col,
                                                   expr=value)
            else:
                only = ast.ReturnStmt(ln=value.ln, col=value.col, value=value)
            body = ast.Block(ln=value.ln, col=value.col, statements=[only],
                             azucar="lambda corta: ': e' es '{ return e; }'")
            short = True
        elif cursor.check(TokenType.L_BRACE):
            from ..grammar.block import parse_block
            # sin el ';' opcional tras la '}': una lambda es una EXPRESION, y
            # el ';' que siga es de la sentencia que la contiene
            body = parse_block(cursor, ctx, trailing_semicolon=False)
            short = False
        else:
            got = cursor.peek()
            raise ParseError.ExpectedTokenError(
                "tras la firma de una lambda va su cuerpo: ': expresion' (la "
                "forma corta) o un bloque '{ ...; return ...; }'; se encontro "
                f"{got.type.name}",
                line=got.ln, column=got.col,
            )
    finally:
        (ctx.loop_depth, ctx.finally_loops, ctx.in_test, ctx.expects,
         ctx.lambda_hides_loop, ctx.lambda_hides_test) = saved
    return ast.Lambda(ln=tok.ln, col=tok.col, params=params,
                      return_type=return_type, body=body, short=short)


PRIMARY_HANDLERS: Dict[TokenType, Callable[[Cursor, ParserContext], ast.Expression]] = {
    TokenType.IDENTIFIER: _identifier,
    TokenType.DOT: lambda c, x: _miembro_del_receptor(c, x),   # '.campo' de un 'with'
    TokenType.DUNDER: _identifier,  # referencia a un nombre '__x__' (p. ej. llamar un hook explicitamente)
    TokenType.INT_LIT: _lit_int,
    TokenType.FLOAT_LIT: _lit_float,
    TokenType.CHAR_LIT: _lit_char,
    TokenType.STRING_LIT: _lit_string,
    TokenType.TRUE: _lit_true,
    TokenType.FALSE: _lit_false,
    TokenType.NULL: _lit_null,
    TokenType.L_PAREN: _grouping,
    TokenType.SIZEOF: _sizeof,
    TokenType.CAST: _cast,
    TokenType.MOVE: _move,
    TokenType.LAMBDA: _lambda,
    # 'make' vuelve a ser un IDENTIFIER corriente.
}


__all__ = [
    "parse_unary", "parse_postfix", "parse_primary",
    "PRIMARY_HANDLERS",
]
