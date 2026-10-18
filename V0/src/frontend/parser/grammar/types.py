"""``type = base_type { type_suffix }`` (EBNF).

::

    base_type   = "int" | "float" | "bool" | "char" | "str" | "void"
                | "type"
                | "fn" "(" [ type { "," type } ] ")" [ "->" type ]
                | "(" type ")"
                | qualified_name
    qualified_name = NAME { "." NAME }        (* NAME = IDENTIFIER | DUNDER *)
    type_suffix = "?" | "ptr" [ "mutable" ]

``ptr`` es un sufijo POSTFIJO (decision de usuario): ``char ptr`` es "puntero
a char" (``char *text`` en C), no ``ptr char``. La forma prefija ya no se
acepta -- ``_parse_base_type`` la reporta con una migracion dirigida.

Los sufijos se aplican de IZQUIERDA A DERECHA, asi que el orden desambigua
lo que en prefijo no se podia escribir:

    char ptr        ->  puntero a char
    char ptr mutable->  puntero a char, escribible a traves de el
    char ptr?       ->  puntero NULLABLE a char        (ptr, luego ?)
    char? ptr       ->  puntero a (char nullable)      (?, luego ptr)
    char ptr ptr    ->  puntero a puntero a char

``ptr T`` es de solo lectura A TRAVES del puntero; ``ptr mutable`` permite
escribir a traves de el (const-correctness estilo C). La mutabilidad del
BINDING es aparte (``var``/``const``, ver statements.py).

``type`` como base_type es el METATIPO (el tipo de un tipo): habilita
``fn _block_def(int len) -> type``. La DECLARACION de un tipo opaco
(``const type int8;``) la parsea ``statements.parse_type_decl``.

``qualified_name`` con puntos (``dt.int8``) referencia un tipo publicado por
una libreria importada: las librerias declaran tipos no nativos
(``int8``/``float16``...) y el consumidor los usa como cualquier otro tipo.
Aqui solo se transporta el nombre completo; recorrer los miembros hasta el
simbolo es de la Semantica (``semantic/type_service.lookup_type_path``).
"""

from __future__ import annotations

from typing import Dict

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

_PRIMITIVE_TOKENS: Dict[TokenType, str] = {
    TokenType.VOID: "void",
    TokenType.BOOL: "bool",
    TokenType.INT: "int",
    TokenType.FLOAT: "float",
    TokenType.CHAR: "char",
    TokenType.STR: "str",
    TokenType.BYTE: "byte",
}


def parse_type(cursor: Cursor, ctx: ParserContext) -> ast.TypeExpr:
    base = _parse_base_type(cursor, ctx)
    # sufijos postfijos, aplicados en el orden en que se escriben (izq->der):
    # 'char? ptr' != 'char ptr?' (ver el docstring del modulo).
    while True:
        tok = cursor.peek()
        if tok.type is TokenType.NULLABLE:
            cursor.advance()
            base = ast.NullableTypeExpr(ln=tok.ln, col=tok.col, inner=base)
        elif tok.type is TokenType.POINTER:
            cursor.advance()
            is_mutable = cursor.match(TokenType.MUTABLE)  # 'T ptr mutable'
            base = ast.PointerTypeExpr(ln=tok.ln, col=tok.col, inner=base,
                                        mutable=is_mutable)
        else:
            return base


def _parse_base_type(cursor: Cursor, ctx: ParserContext) -> ast.TypeExpr:
    tok = cursor.peek()

    name = _PRIMITIVE_TOKENS.get(tok.type)
    if name is not None:
        cursor.advance()
        return ast.PrimitiveTypeExpr(ln=tok.ln, col=tok.col, name=name)

    if tok.type is TokenType.ERRORTYPE:
        # 'error T' (union T-o-error) o 'error' a secas. El inner es OTRO
        # 'type' completo; ausente si lo que sigue no arranca un tipo
        # ('error n;' -> 'error' solo, 'n' es el nombre del binding).
        cursor.advance()
        inner = _parse_error_inner(cursor, ctx)
        return ast.ErrorTypeExpr(ln=tok.ln, col=tok.col, inner=inner)

    if tok.type is TokenType.TYPE:
        # el METATIPO: 'fn f() -> type' devuelve un tipo como valor.
        cursor.advance()
        return ast.MetaTypeExpr(ln=tok.ln, col=tok.col)

    if tok.type is TokenType.FUNCTION:
        return _parse_function_type(cursor, ctx)

    if tok.type is TokenType.L_PAREN:
        # tipo ENTRE PARENTESIS: existe por el tipo funcion. Lo que sigue a
        # su flecha es del retorno ('fn(int) -> int?' devuelve 'int?'), asi
        # que una funcion que puede faltar solo se puede escribir agrupando:
        # '(fn(int) -> int)?'. Los sufijos de fuera los aplica 'parse_type'.
        cursor.advance()
        inner = parse_type(cursor, ctx)
        cursor.expect(TokenType.R_PAREN)
        return inner

    if tok.type is TokenType.IDENTIFIER and tok.lexeme == "self":
        # 'self' en posicion de tipo es el placeholder del tipo que hara
        # '@impl' (solo valido dentro de un prototipo de trait; la Semantica
        # lo rechaza en otra posicion). NO es keyword: 'self' sigue usable como
        # nombre de variable/parametro. No se cualifica ('self.x' no es un tipo).
        cursor.advance()
        return ast.SelfTypeExpr(ln=tok.ln, col=tok.col)

    if tok.type is TokenType.IDENTIFIER or tok.type is TokenType.DUNDER:
        # DUNDER: un tipo nominal declarado con nombre '__x__' (ver
        # Cursor.expect_name) tambien debe poder REFERENCIARSE como tipo
        # (p. ej. '__opaque__ ptr'), no solo declararse.
        cursor.advance()
        name = _qualified_name(cursor, tok.lexeme)
        # ARGUMENTOS DE TIPO ('Vector<int>'). Aqui '<' no puede ser una
        # comparacion —estamos en posicion de TIPO, no de expresion—, asi que
        # no hay ambiguedad estilo C++ que resolver: si sigue un '<', son
        # argumentos. Reusa la misma regla que 'cast<T>(x)'.
        args = parse_type_args(cursor, ctx) if cursor.check(TokenType.LESS) else []
        return ast.NominalTypeExpr(ln=tok.ln, col=tok.col, name=name, args=args)

    if tok.type is TokenType.POINTER:
        # forma prefija ('ptr char') retirada: 'ptr' es sufijo postfijo.
        raise ParseError.MissingTypeAnnotationError(
            "'ptr' es un sufijo postfijo: escribe 'T ptr' en vez de 'ptr T' "
            "(p. ej. 'char ptr text', no 'ptr char text')",
            line=tok.ln, column=tok.col,
        )

    raise ParseError.MissingTypeAnnotationError(
        f"se esperaba un tipo, se encontro {tok.type.name}",
        line=tok.ln, column=tok.col,
    )


def _parse_function_type(cursor: Cursor, ctx: ParserContext) -> ast.TypeExpr:
    """``"fn" "(" [ type { "," type } ] ")" [ "->" type ]`` -- un TIPO funcion.

    En posicion de tipo, ``fn`` va seguido de ``(``; en una declaracion, de
    un nombre. Con eso basta para distinguirlas sin mirar mas lejos.

    Sin flecha, el retorno es ``void``, igual que al declarar una funcion: la
    misma ausencia significa lo mismo en los dos sitios. Lo que se escribe
    tras la flecha es un ``type`` COMPLETO, con sus sufijos: por eso
    ``fn(int) -> int?`` devuelve ``int?`` y para una funcion que puede faltar
    hacen falta parentesis (``(fn(int) -> int)?``).
    """
    tok = cursor.advance()  # 'fn'
    if not cursor.check(TokenType.L_PAREN):
        nxt = cursor.peek()
        raise ParseError.MissingTypeAnnotationError(
            "un tipo funcion se escribe 'fn(<parametros>) -> <retorno>' "
            f"(p. ej. 'fn(int, str) -> bool'); tras 'fn' se encontro "
            f"{nxt.type.name}",
            line=nxt.ln, column=nxt.col,
        )
    cursor.advance()  # '('
    params = []
    if not cursor.check(TokenType.R_PAREN):
        params.append(_param_type(cursor, ctx))
        while cursor.match(TokenType.COMMA):
            params.append(_param_type(cursor, ctx))
    cursor.expect(TokenType.R_PAREN)
    if cursor.match(TokenType.ARROW):
        ret = parse_type(cursor, ctx)
    else:
        ret = ast.PrimitiveTypeExpr(ln=tok.ln, col=tok.col, name="void")
    return ast.FunctionTypeExpr(ln=tok.ln, col=tok.col, params=params, ret=ret)


def _param_type(cursor: Cursor, ctx: ParserContext) -> ast.TypeExpr:
    """Un parametro de un tipo funcion: solo su TIPO.

    Si tras el tipo viene un nombre, lo escrito es una DECLARACION a la que le
    falta el suyo (``fn (int x) -> int { ... }``): se dice eso, que es lo que
    falta, en vez de un "se esperaba ')'" que apunta al sintoma."""
    t = parse_type(cursor, ctx)
    nxt = cursor.peek()
    if nxt.type is TokenType.IDENTIFIER:
        raise ParseError.ExpectedTokenError(
            "a la declaracion de la funcion le falta el NOMBRE "
            "('fn nombre(int x) -> ...'); 'fn(' sin nombre es un TIPO "
            "funcion, y sus parametros solo llevan tipos ('fn(int) -> int')",
            line=nxt.ln, column=nxt.col,
        )
    return t


# tokens que pueden ARRANCAR un tipo base (para decidir el inner de 'error').
_TYPE_STARTERS = frozenset({
    *_PRIMITIVE_TOKENS, TokenType.TYPE, TokenType.ERRORTYPE,
    TokenType.IDENTIFIER, TokenType.DUNDER,
    TokenType.FUNCTION, TokenType.L_PAREN,
})


def _parse_error_inner(cursor: Cursor, ctx: ParserContext):
    """El tipo envuelto por ``error``, o ``None`` si ``error`` va solo.

    Regla GREEDY sin backtracking: hay inner sii el token siguiente arranca
    un tipo. Asi ``error int n`` -> ``error<int>`` + nombre ``n``;
    ``fn f() -> error`` (sigue ``;``) -> ``error`` sola. La unica forma no
    escribible es un binding de tipo ``error`` puro seguido de nombre
    (``error n;``): usa ``error void n;`` o reordena — caso marginal."""
    if cursor.peek().type in _TYPE_STARTERS:
        return parse_type(cursor, ctx)
    return None


def parse_type_params(cursor: Cursor, ctx: ParserContext):
    """``type_params = [ "<" type_param { "," type_param } ">" ]`` -- los
    PARAMETROS de un tipo generico, pegados a su nombre
    (``struct { ... } Vector<T>;``), cada uno con sus COTAS opcionales::

        type_param = IDENTIFIER [ ":" bound { "+" bound } ]
        bound      = NAME { "." NAME }

    Devuelve ``(nombres, cotas)``: la lista de nombres de siempre (lo que
    viaja al HIR) y ``{nombre: [TypeBound, ...]}`` solo con los que llevan
    alguna. Las cotas no cambian ningun nombre: ``<T: Ord>`` declara el mismo
    ``T`` que ``<T>``, y lo que añade lo comprueba la Semantica.

    Espeja a :func:`parse_type_args` pero admite solo NOMBRES: un parametro
    es un nombre que se va a ligar, no un tipo ya escrito. Escribir
    ``Vector<int>`` en una DECLARACION seria declarar un parametro llamado
    'int', que no significa nada; se rechaza con un mensaje que lo dice.
    """
    if not cursor.check(TokenType.LESS):
        return [], {}
    cursor.advance()
    params: list[str] = []
    bounds: dict = {}
    while True:
        name = _parametro(cursor)
        params.append(name)
        if cursor.match(TokenType.COLON):
            written = [_bound(cursor)]
            while cursor.match(TokenType.PLUS):
                written.append(_bound(cursor))
            # 'T: Ord + Ord' no es un error de sintaxis; lo dice la Semantica
            bounds[name] = written
        if not cursor.match(TokenType.COMMA):
            break
    cursor.expect(TokenType.GREATER)
    return params, bounds


def _bound(cursor: Cursor) -> ast.TypeBound:
    """``NAME { "." NAME }`` -- una cota: un trait o un concepto nativo.

    Solo un nombre: una cota no es un tipo (``T: int`` no promete nada que se
    pueda comprobar), y ``T: Caja<int>`` no es una forma del lenguaje."""
    tok = cursor.peek()
    if tok.type is not TokenType.IDENTIFIER:
        raise ParseError.MissingTypeAnnotationError(
            f"una cota es el NOMBRE de un trait o de un concepto ('Eq', 'Ord', "
            f"'Hash', 'Print'), como en '<T: Ord + Hash>'; se encontro "
            f"'{tok.lexeme or tok.type.name}'",
            line=tok.ln, column=tok.col,
        )
    cursor.advance()
    return ast.TypeBound(ln=tok.ln, col=tok.col,
                         name=_qualified_name(cursor, tok.lexeme))


def _parametro(cursor: Cursor) -> str:
    tok = cursor.peek()
    if tok.type is not TokenType.IDENTIFIER:
        raise ParseError.MissingTypeAnnotationError(
            f"un parametro de tipo es un NOMBRE por ligar, no un tipo ya "
            f"escrito: '{tok.lexeme}' no sirve. Escribe 'Vector<T>' para "
            f"declarar el generico y 'Vector<int>' para usarlo",
            line=tok.ln, column=tok.col,
        )
    cursor.advance()
    return tok.lexeme


def parse_type_args(cursor: Cursor, ctx: ParserContext) -> list[ast.TypeExpr]:
    """``type_args = "<" type { "," type } ">"`` -- posicion de ARGUMENTOS DE
    TIPO (EBNF).

    Regla COMPARTIDA por toda construccion que parametrice con tipos: hoy la
    usa ``cast<T>(expr)`` (unica forma nativa); las librerias la reutilizaran
    para genericos (``vec<int>``) sin redefinir la sintaxis de los angulos.

    Aqui ``<``/``>`` no son comparaciones: el llamador YA decidio que esta en
    posicion de argumentos de tipo (p. ej. tras la keyword ``cast``), asi que
    no hay ambiguedad estilo C++ que resolver en este nivel.
    """
    cursor.expect(TokenType.LESS)
    args = [parse_type(cursor, ctx)]
    while cursor.match(TokenType.COMMA):
        args.append(parse_type(cursor, ctx))
    cursor.expect(TokenType.GREATER)
    return args


def _qualified_name(cursor: Cursor, head: str) -> str:
    """``head { "." NAME }`` -> ``"dt"`` / ``"dt.int8"`` / ``"d_types.dt.int8"``.

    El primer nombre ya viene consumido. Sin puntos (el caso comun) no se
    construye ninguna lista: se devuelve ``head`` tal cual.
    """
    if not cursor.check(TokenType.DOT):
        return head
    parts = [head]
    while cursor.match(TokenType.DOT):
        parts.append(cursor.expect_name().lexeme)
    return ".".join(parts)


__all__ = ["parse_type", "parse_type_args"]
