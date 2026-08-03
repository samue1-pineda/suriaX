"""Scanner de literales de cadena (STRING), f-string (interpolada) y CHAR.

 - cadenas planas: delimitadas por comillas dobles ``"..."``. **No**
   interpolan: ``{`` y ``}`` son caracteres literales como cualquier otro
   (``"hola {x}"`` es exactamente ese texto). Decision de diseno: la
   interpolacion es OPT-IN, asi ``print`` (texto plano) y ``printf``
   (formateado) son operaciones distintas.
 - f-strings: prefijo explicito ``f"..."``. Soportan **interpolacion**:
   ``f"hola{a}"`` descompone el valor en segmentos de texto literal e
   interpolaciones ``{expr}`` (ver :class:`StringValue`). Para una llave
   literal dentro de una f-string se escribe ``{{`` o ``}}`` (estilo
   f-string de Python).
 - caracteres: delimitados por comillas simples ``'x'`` (un solo code point,
   sin interpolacion).

Ambas formas de cadena producen el mismo ``TokenType.STRING_LIT`` con un
:class:`StringValue` como valor: las fases posteriores distinguen por
``StringValue.is_interpolated``, no por el prefijo (el prefijo solo habilita
el mecanismo, no cambia el tipo del literal: siempre ``str``).

Soporta secuencias de escape basicas. Una cadena/caracter sin cerrar produce
:class:`UnterminatedStringError` (LEX003); un escape no reconocido produce
:class:`InvalidEscapeSequenceError` (LEX005); un literal de caracter vacio o de
mas de un code point produce :class:`InvalidCharacterLiteralError` (LEX012);
una interpolacion sin cerrar (``{`` sin ``}``) en una f-string produce
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
    """Cadena PLANA ``"..."``: sin interpolacion, ``{``/``}`` literales."""
    return _scan_quoted(lx, interpolate=False, prefix_len=0)


def scan_fstring(lx) -> Token:
    """F-string ``f"..."``: interpolacion ``{expr}`` y escapes ``{{`` ``}}``.

    El dispatcher del lexer la reconoce por el par ``f`` + ``"`` adyacentes
    (``lx.pos`` apunta a la ``f``). El lexema del token incluye el prefijo.
    """
    return _scan_quoted(lx, interpolate=True, prefix_len=1)


def _scan_quoted(lx, *, interpolate: bool, prefix_len: int) -> Token:
    """Nucleo compartido de ``scan_string``/``scan_fstring``: una sola pasada.

    ``prefix_len`` es cuantos caracteres de prefijo (``f``) preceden a la
    comilla de apertura; el lexema del token los incluye.
    """
    src = lx.source
    n = lx.length
    start = lx.pos
    start_col = lx.col

    pos = start + prefix_len + 1  # saltar prefijo + comilla de apertura
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

        # llaves: solo tienen significado en una f-string
        if interpolate and ch == "{":
            if pos + 1 < n and src[pos + 1] == "{":
                buf.append("{")
                pos += 2
                continue
            # interpolacion: leer hasta '}' balanceado en la misma linea
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

        # llave de cierre en f-string: solo valida como '}}' literal
        if interpolate and ch == "}":
            if pos + 1 < n and src[pos + 1] == "}":
                buf.append("}")
                pos += 2
                continue
            lx.jump_to(_string_end(src, n, pos + 1))
            raise lex_error.InvalidTokenError(
                "'}' suelto en una f-string; usa '}}' para una llave literal",
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
