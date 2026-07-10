"""Scanner de literales de cadena (STRING) y de caracter (CHAR).

 - cadenas: delimitadas por comillas dobles ``"..."``. Soportan
   **interpolacion**: ``"hola{a}"`` descompone el valor en segmentos de texto
   literal e interpolaciones ``{expr}`` (ver :class:`StringValue`). Para una
   llave literal se escribe ``{{`` o ``}}`` (estilo f-string de Python).
 - caracteres: delimitados por comillas simples ``'x'`` (un solo code point,
   sin interpolacion).

Soporta secuencias de escape basicas. Una cadena/caracter sin cerrar produce
:class:`UnterminatedStringError` (LEX003); un escape no reconocido produce
:class:`InvalidEscapeSequenceError` (LEX005); un literal de caracter vacio o de
mas de un code point produce :class:`InvalidCharacterLiteralError` (LEX012);
una interpolacion sin cerrar (``{`` sin ``}``) produce
:class:`InvalidTokenError` (LEX002).
"""

from __future__ import annotations

try:
    from include.t_types import Interp, StringValue, Token, TokenType
    from error_handler import lex_error
except ImportError:  # pragma: no cover
    from t_types import Interp, StringValue, Token, TokenType  # type: ignore
    import lex_error  # type: ignore


_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "0": "\0",
    "\\": "\\",
    '"': '"',
    "'": "'",
}


def _string_end(src: str, n: int, pos: int) -> int:
    """Posicion tras el cierre del string actual (recuperacion de errores).

    Avanza desde ``pos`` hasta justo despues de la comilla de cierre ``"`` o,
    si no la hay, hasta el fin de linea. Asi, ante un error *dentro* de un
    string ya abierto, el lexer reanuda en un limite sano y no interpreta el
    resto del literal como codigo (evita errores en cascada).
    """
    while pos < n and src[pos] != "\n":
        if src[pos] == "\\":
            pos += 2
            continue
        if src[pos] == '"':
            return pos + 1
        pos += 1
    return pos


def scan_string(lx) -> Token:
    """Reconoce ``"..."`` con interpolacion ``{expr}`` y escapes ``{{`` ``}}``.

    El ``value`` del token es un :class:`StringValue` con los segmentos en
    orden. Se construye en una sola pasada.
    """
    src = lx.source
    n = lx.length
    start = lx.pos
    start_col = lx.col

    pos = start + 1  # saltar la comilla de apertura
    parts: list = []          # segmentos finales (str | Interp)
    buf: list[str] = []       # texto literal acumulado

    def flush_literal() -> None:
        if buf:
            parts.append("".join(buf))
            buf.clear()

    while pos < n:
        ch = src[pos]

        if ch == '"':
            pos += 1
            flush_literal()
            lexeme = src[start:pos]
            lx.jump_to(pos)
            return Token(
                TokenType.STRING_LIT, lexeme, StringValue(tuple(parts)),
                lx.ln, start_col,
            )

        if ch == "\n":
            break  # salto de linea sin cerrar -> error abajo

        if ch == "\\":
            pos += 1
            if pos >= n:
                break
            esc = src[pos]
            if esc not in _ESCAPES:
                lx.jump_to(pos + 1)
                raise lex_error.InvalidEscapeSequenceError(
                    f"secuencia de escape no reconocida: '\\{esc}'",
                    line=lx.ln,
                    column=start_col,
                    file=lx.file,
                )
            buf.append(_ESCAPES[esc])
            pos += 1
            continue

        # llave de apertura: interpolacion o '{{' literal
        if ch == "{":
            if pos + 1 < n and src[pos + 1] == "{":
                buf.append("{")
                pos += 2
                continue
            # interpolacion: leer hasta '}' (sin anidamiento de llaves)
            flush_literal()
            expr_start = pos + 1
            expr_col = expr_start - lx._line_start + 1
            depth = 1
            j = expr_start
            while j < n and src[j] != "\n":
                if src[j] == "{":
                    depth += 1
                elif src[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j >= n or src[j] != "}":
                lx.jump_to(_string_end(src, n, j))
                raise lex_error.InvalidTokenError(
                    "interpolacion sin cerrar: falta '}'",
                    line=lx.ln,
                    column=start_col,
                    file=lx.file,
                )
            expr = src[expr_start:j].strip()
            if not expr:
                lx.jump_to(_string_end(src, n, j + 1))
                raise lex_error.InvalidTokenError(
                    "interpolacion vacia: '{}'",
                    line=lx.ln,
                    column=start_col,
                    file=lx.file,
                )
            parts.append(Interp(expr, expr_col))
            pos = j + 1
            continue

        # llave de cierre: solo valida como '}}' literal
        if ch == "}":
            if pos + 1 < n and src[pos + 1] == "}":
                buf.append("}")
                pos += 2
                continue
            lx.jump_to(_string_end(src, n, pos + 1))
            raise lex_error.InvalidTokenError(
                "'}' suelto en un string; usa '}}' para una llave literal",
                line=lx.ln,
                column=start_col,
                file=lx.file,
            )

        buf.append(ch)
        pos += 1

    # se llego aqui sin encontrar la comilla de cierre
    lx.jump_to(pos)
    raise lex_error.UnterminatedStringError(
        "literal sin delimitador de cierre",
        line=lx.ln,
        column=start_col,
        file=lx.file,
    )


def scan_char(lx) -> Token:
    """Reconoce ``'x'``: exactamente un code point Unicode (sin interpolacion)."""
    src = lx.source
    n = lx.length
    start = lx.pos
    start_col = lx.col

    pos = start + 1  # saltar la comilla de apertura
    chars: list[str] = []

    while pos < n:
        ch = src[pos]
        if ch == "'":
            pos += 1
            lexeme = src[start:pos]
            lx.jump_to(pos)
            value = "".join(chars)
            if len(value) != 1:
                raise lex_error.InvalidCharacterLiteralError(
                    "un literal de caracter debe contener exactamente un code point",
                    line=lx.ln,
                    column=start_col,
                    file=lx.file,
                )
            return Token(TokenType.CHAR_LIT, lexeme, value, lx.ln, start_col)

        if ch == "\n":
            break

        if ch == "\\":
            pos += 1
            if pos >= n:
                break
            esc = src[pos]
            if esc not in _ESCAPES:
                lx.jump_to(pos + 1)
                raise lex_error.InvalidEscapeSequenceError(
                    f"secuencia de escape no reconocida: '\\{esc}'",
                    line=lx.ln,
                    column=start_col,
                    file=lx.file,
                )
            chars.append(_ESCAPES[esc])
            pos += 1
            continue

        chars.append(ch)
        pos += 1

    lx.jump_to(pos)
    raise lex_error.UnterminatedStringError(
        "literal sin delimitador de cierre",
        line=lx.ln,
        column=start_col,
        file=lx.file,
    )
