"""Scanner de directivas y utilidades de comentarios.

 - directivas: comienzan con ``#``. El lexer emite un unico token
   ``DIRECTIVE`` cuyo ``value`` es el nombre de la directiva (``import``,
   ``export``, ``extern``, ``test``, ``from``). La SEMANTICA de cada directiva
   vive en el parser; el lexer solo valida que el nombre exista.

 - bloque extern crudo: ``#extern cpp{ ... }`` para interoperabilidad C++. El
   contenido entre llaves NO se tokeniza con las reglas de suriaX (es C++); se
   captura como texto crudo en un token ``RAW_BLOCK``. El scanner de directivas
   emite ``DIRECTIVE('extern')`` + ``IDENTIFIER('cpp')`` + ``RAW_BLOCK(<c++>)``.

 - comentarios: ``//`` (una linea) y ``/- -/`` (multilinea). El salto de
   comentarios lo invoca el lexer en su bucle principal, en el mismo paso de
   tokenizacion (sin segunda pasada ni copia del texto).
"""

from __future__ import annotations

try:
    from include.t_types import DIRECTIVES, Token, TokenType
    from error_handler import lex_error
except ImportError:  # pragma: no cover
    from t_types import DIRECTIVES, Token, TokenType  # type: ignore
    import lex_error  # type: ignore

from .ident import is_ident_continue, is_ident_start


def scan_directive(lx):
    """Reconoce ``#nombre`` y emite un token DIRECTIVE.

    Caso especial: ``#extern cpp{ ... }`` captura el cuerpo como ``RAW_BLOCK``
    (ver :func:`_scan_extern_block`). En ese caso, este scanner agrega los tres
    tokens en orden (``DIRECTIVE('extern')``, ``IDENTIFIER('cpp')``,
    ``RAW_BLOCK``) directamente a ``lx.tokens`` y devuelve ``None``.
    """
    src = lx.source
    n = lx.length
    start = lx.pos
    start_col = lx.col

    pos = start + 1  # saltar '#'
    name_start = pos
    if pos < n and is_ident_start(src[pos]):
        pos += 1
        while pos < n and is_ident_continue(src[pos]):
            pos += 1

    name = src[name_start:pos]
    lexeme = src[start:pos]

    if name not in DIRECTIVES:
        lx.jump_to(pos)
        raise lex_error.InvalidDirectiveError(
            f"directiva no reconocida: '#{name}'",
            line=lx.ln,
            column=start_col,
            file=lx.file,
        )

    directive_tok = Token(TokenType.DIRECTIVE, lexeme, name, lx.ln, start_col)

    # '#extern cpp{ ... }': bloque crudo de interoperabilidad C++.
    if name == "extern" and _peek_extern_cpp(src, n, pos):
        lx.jump_to(pos)
        lx.tokens.append(directive_tok)   # DIRECTIVE('extern') va primero
        _scan_extern_block(lx)            # luego IDENTIFIER('cpp') + RAW_BLOCK
        return None

    lx.jump_to(pos)
    return directive_tok


def _peek_extern_cpp(src: str, n: int, pos: int) -> bool:
    """¿Lo que sigue a ``#extern`` es ``cpp``, su ``requires`` opcional y ``{``?

    La clausula ``requires(...)`` va entre medias, asi que hay que saltarla
    para decidir: sin eso el lexer no reconocia el bloque y acababa
    tokenizando el C++ como si fuera suriaX.
    """
    i = pos
    while i < n and src[i] in " \t":
        i += 1
    if src[i:i + 3] != "cpp":
        return False
    i += 3
    while i < n and src[i] in " \t\r\n":
        i += 1
    if src.startswith("requires", i):
        j = i + len("requires")
        while j < n and src[j] in " \t\r\n":
            j += 1
        if j < n and src[j] == "(":
            cierre = src.find(")", j)
            if cierre == -1:
                return False
            i = cierre + 1
            while i < n and src[i] in " \t\r\n":
                i += 1
    return i < n and src[i] == "{"


def _scan_requires(lx, i: int) -> int:
    """``requires("-lX11", "-I/opt/inc")`` tras ``cpp``: banderas de enlazado.

    Se escanea AQUI, dentro del scanner del bloque crudo, y no con el bucle
    general del lexer, porque este scanner se lleva el control hasta la ``}``
    de cierre: dejar salir y volver a entrar habria partido en dos un token
    que se captura de una pieza.

    La lista es de literales de cadena y nada mas, asi que se extraen tal
    cual y se emiten como STRING corrientes — el parser los lee con el cursor
    normal. Devuelve la posicion tras el ``)``, o la de entrada si no habia
    ``requires``.
    """
    src = lx.source
    n = lx.length
    j = i
    while j < n and src[j] in " \t\r\n":
        j += 1
    if not src.startswith("requires", j):
        return i
    k = j + len("requires")
    while k < n and src[k] in " \t\r\n":
        k += 1
    if k >= n or src[k] != "(":
        return i          # 'requires' sin '(': no es la clausula, no se toca

    lx.jump_to(j)
    lx.tokens.append(Token(TokenType.IDENTIFIER, "requires", "requires",
                           lx.ln, lx.col))
    cierre = src.find(")", k)
    if cierre == -1:
        lx.jump_to(n)
        raise lex_error.UnterminatedExternBlockError(
            "'requires(' de un '#extern' sin cerrar",
            line=lx.ln, column=lx.col, file=lx.file,
        )
    dentro = src[k + 1:cierre]
    pos = 0
    while True:
        abre = -1
        for comilla in ('"', "'"):
            hallado = dentro.find(comilla, pos)
            if hallado != -1 and (abre == -1 or hallado < abre):
                abre = hallado
                delim = comilla
        if abre == -1:
            break
        fin = dentro.find(delim, abre + 1)
        if fin == -1:
            break
        texto = dentro[abre + 1:fin]
        lx.jump_to(k + 1 + abre)
        lx.tokens.append(Token(TokenType.STRING_LIT, delim + texto + delim, texto,
                               lx.ln, lx.col))
        pos = fin + 1
    lx.jump_to(cierre + 1)
    return cierre + 1


def _scan_extern_block(lx) -> None:
    """Captura ``cpp{ ... }`` tras ``#extern`` como IDENTIFIER + RAW_BLOCK.

    Asume que ``lx.pos`` esta justo despues de ``#extern`` (el token
    ``DIRECTIVE('extern')`` ya fue agregado). Agrega los tokens
    ``IDENTIFIER('cpp')`` y ``RAW_BLOCK(<c++ crudo>)`` a ``lx.tokens``. El
    contenido se toma literal (no se tokeniza); las llaves internas se
    balancean para soportar C++ con bloques anidados.
    """
    src = lx.source
    n = lx.length

    # ubicar 'cpp'
    i = lx.pos
    while i < n and src[i] in " \t":
        i += 1
    cpp_col = i - lx._line_start + 1
    lx.jump_to(i)
    cpp_tok = Token(TokenType.IDENTIFIER, "cpp", "cpp", lx.ln, cpp_col)
    lx.tokens.append(cpp_tok)

    # requisitos NATIVOS de la unidad, si los declara
    i += 3  # saltar 'cpp'
    i = _scan_requires(lx, i)

    # ubicar la '{' de apertura
    while i < n and src[i] in " \t\r\n":
        i += 1
    lx.jump_to(i)            # actualiza ln/col hasta la '{'
    brace_col = lx.col
    brace_ln = lx.ln
    body_start = i + 1       # contenido tras '{'

    depth = 1
    j = body_start
    while j < n:
        c = src[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1

    if j >= n or depth != 0:
        lx.jump_to(n)
        raise lex_error.UnterminatedExternBlockError(
            "bloque '#extern cpp{ ... }' sin cerrar",
            line=brace_ln,
            column=brace_col,
            file=lx.file,
        )

    raw = src[body_start:j]
    lexeme = src[i:j + 1]    # '{ ... }' completo
    lx.jump_to(j + 1)        # consumir la '}' de cierre
    lx.tokens.append(
        Token(TokenType.RAW_BLOCK, lexeme, raw, brace_ln, brace_col)
    )


def scan_decorator(lx) -> Token:
    """Reconoce ``@nombre`` y emite un token DECORATOR.

    A diferencia de OWNER/ADDRESS, el decorador exige un identificador valido
    justo despues del ``@``. Si falta, produce
    :class:`InvalidDecoratorError` (LEX013).
    """
    src = lx.source
    n = lx.length
    start = lx.pos
    start_col = lx.col

    pos = start + 1  # saltar '@'
    name_start = pos
    if pos < n and is_ident_start(src[pos]):
        pos += 1
        while pos < n and is_ident_continue(src[pos]):
            pos += 1
    else:
        lx.jump_to(pos)
        raise lex_error.InvalidDecoratorError(
            "se esperaba un identificador despues de '@'",
            line=lx.ln,
            column=start_col,
            file=lx.file,
        )

    name = src[name_start:pos]
    lexeme = src[start:pos]
    lx.jump_to(pos)
    return Token(TokenType.DECORATOR, lexeme, name, lx.ln, start_col)


def skip_line_comment(lx) -> None:
    """Salta ``// ...`` hasta el fin de linea (sin consumir el '\\n')."""
    src = lx.source
    n = lx.length
    pos = lx.pos + 2  # saltar '//'
    while pos < n and src[pos] != "\n":
        pos += 1
    lx.jump_to(pos)


def skip_block_comment(lx) -> None:
    """Salta ``/- ... -/`` (puede abarcar varias lineas).

    Lanza :class:`UnterminatedCommentError` (LEX004) si no se cierra.
    """
    src = lx.source
    n = lx.length
    start_col = lx.col
    start_ln = lx.ln
    pos = lx.pos + 2  # saltar '/-'

    while pos < n - 1:
        if src[pos] == "-" and src[pos + 1] == "/":
            lx.jump_to(pos + 2)
            return
        pos += 1

    # llegamos al final sin cerrar
    lx.jump_to(n)
    raise lex_error.UnterminatedCommentError(
        "comentario multilinea sin cerrar",
        line=start_ln,
        column=start_col,
        file=lx.file,
    )
