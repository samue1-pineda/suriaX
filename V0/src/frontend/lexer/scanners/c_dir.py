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
    """¿Lo que sigue a ``#extern`` es ``cpp`` (con espacios) y luego ``{``?"""
    i = pos
    while i < n and src[i] in " \t":
        i += 1
    if src[i:i + 3] != "cpp":
        return False
    i += 3
    while i < n and src[i] in " \t\r\n":
        i += 1
    return i < n and src[i] == "{"


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

    # ubicar la '{' de apertura
    i += 3  # saltar 'cpp'
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
