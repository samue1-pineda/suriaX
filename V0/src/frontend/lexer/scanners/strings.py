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
   f-string de Python). Lo que va entre ``{`` y ``}`` es CODIGO, como en
   Python 3.12 y C#: un literal dentro se escribe tal cual (``f"{len("ab")}"``,
   ``f"{'}'}"``) y sus comillas y llaves no cierran nada; un ``\\`` fuera de
   un literal es :class:`InvalidEscapeSequenceError` (LEX005), con la forma
   correcta en el mensaje (ver :func:`find_interpolation_end`).
 - caracteres: delimitados por comillas simples ``'x'`` (un solo code point,
   sin interpolacion). NO se concatenan entre si: son ``CHAR_LIT``, otro
   token, igual que en C.

Dos literales de cadena ADYACENTES forman uno solo (``"parte uno " "parte
dos"``), como en C, C++ y Python. La fusion la hace el lexer
(:func:`join_adjacent`), que es donde no cuesta nada: con ``+`` el mismo
resultado exigia una concatenacion en ejecucion.

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


def _char_end(src: str, n: int, pos: int) -> int:
    """Como :func:`_string_end`, para un literal de caracter (``'``)."""
    while pos < n and src[pos] != "\n":
        if src[pos] == "\\":
            pos += 2
            continue
        if src[pos] == "'":
            return pos + 1
        pos += 1
    return pos


def _opens_fstring(src: str, j: int, lower: int) -> bool:
    """¿La comilla de ``src[j]`` abre una f-string (``f"``)? Solo si la ``f``
    EMPIEZA un token, igual que en el lexer: en ``xf"..."`` la ``f`` es parte
    del nombre y la cadena es plana."""
    if j - 1 < lower or src[j - 1] != "f":
        return False
    before = src[j - 2] if j - 2 >= 0 else ""
    return not (before.isalnum() or before == "_")


def find_interpolation_end(src: str, n: int, start: int) -> tuple:
    """Donde cierra la interpolacion que empieza en ``start`` (tras su ``{``).

    Devuelve ``(cierre, barra)``: ``cierre`` es la posicion de su ``}`` (o -1
    si la linea termina antes) y ``barra``, la de un ``\\`` escrito FUERA de
    un literal (o -1).

    La regla (la de Python 3.12 y C#): lo que va entre ``{`` y ``}`` es
    CODIGO, y un literal dentro es un literal entero. Su contenido no cuenta:
    en ``f"{'}'}"`` la llave del caracter no cierra nada, y en
    ``f"{len("ab")}"`` la comilla de ``"ab"`` no cierra la cadena de fuera.
    Por eso las comillas de dentro se escriben SIN escapar; un ``\\`` fuera
    de un literal no significa nada ahi (la expresion no es texto de la
    cadena) y se informa aparte, con lo que hay que escribir.

    Una f-string dentro de la interpolacion tiene a su vez interpolaciones:
    se recorren con una pila explicita (sin recursion de Python), y nada de
    esto cruza un salto de linea.
    """
    # cada entrada: [clase, profundidad de llaves]; clase "hole" (codigo),
    # "str" (cadena plana) o "fstr" (f-string anidada)
    stack = [["hole", 1]]
    j = start
    while j < n:
        c = src[j]
        if c == "\n":
            return -1, -1
        top = stack[-1]
        if top[0] == "hole":
            if c == '"':
                stack.append(["fstr" if _opens_fstring(src, j, start) else "str", 0])
            elif c == "'":
                # literal de caracter: hasta su comilla, con escapes
                k = j + 1
                while k < n and src[k] not in "'\n":
                    k += 2 if src[k] == "\\" else 1
                if k >= n or src[k] != "'":
                    return -1, -1
                j = k
            elif c == "\\":
                return -1, j
            elif c == "{":
                top[1] += 1
            elif c == "}":
                top[1] -= 1
                if top[1] == 0:
                    stack.pop()
                    if not stack:
                        return j, -1
            j += 1
            continue
        # dentro de un literal de cadena (plano o f-string anidada)
        if c == "\\":
            j += 2
            continue
        if c == '"':
            stack.pop()
        elif top[0] == "fstr" and c in "{}":
            if src[j + 1:j + 2] == c:      # '{{' / '}}' literales
                j += 2
                continue
            if c == "{":
                stack.append(["hole", 1])
        j += 1
    return -1, -1


def join_adjacent(left: Token, right: Token) -> Token:
    """Funde dos ``STRING_LIT`` adyacentes en uno solo.

    Dos literales pegados forman uno, como en C, C++ y Python: es la forma
    natural de partir un mensaje largo en varias lineas, y hacerlo aqui no
    cuesta nada — con ``+`` costaba una concatenacion en EJECUCION para algo
    que se sabe al leer el archivo.

    La regla que decide el caso dudoso —pegar una ``f""`` con una ``""``— es
    que **cada literal conserva la suya**: la interpolacion ya se resolvio al
    escanear cada uno por separado, asi que ``f"a{x}" "b"`` interpola ``{x}``
    y ``f"a" "{x}"`` NO interpola nada (en una cadena plana ``{`` es un
    caracter). El prefijo gobierna su propio literal, no la union. Cualquier
    otra regla obligaria a mirar los vecinos para saber que significa un
    literal.

    Los segmentos de texto contiguos se funden: la union tiene la MISMA forma
    que habria tenido un solo literal escrito de una vez.
    """
    parts = list(left.value.parts)
    for part in right.value.parts:
        if isinstance(part, str) and parts and isinstance(parts[-1], str):
            parts[-1] += part
        else:
            parts.append(part)
    # posicion y linea: las del PRIMER literal, que es donde empieza el valor.
    return Token(
        TokenType.STRING_LIT,
        f"{left.lexeme} {right.lexeme}",
        StringValue(tuple(parts)),
        left.ln, left.col,
    )


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
                # se reanuda tras el cierre del literal: reanudar en mitad dejaba su
                # comilla de cierre abriendo otro literal (un LEX003 en cascada)
                lx.jump_to(_string_end(src, n, pos + 1))
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
            # interpolacion: hasta su '}', en la misma linea, saltando los
            # literales que haya dentro (ver find_interpolation_end)
            flush_literal()
            expr_start = pos + 1
            j, backslash = find_interpolation_end(src, n, expr_start)
            if backslash >= 0:
                # se reanuda tras la cadena ENTERA: quien escapa las comillas
                # de dentro las escribio como texto de la cadena, asi que el
                # recorrido con escapes encuentra su cierre de verdad
                bad_col = backslash - lx._line_start + 1
                lx.jump_to(_string_end(src, n, expr_start))
                raise lex_error.InvalidEscapeSequenceError(
                    "'\\' dentro de una interpolacion: lo que va entre '{' y "
                    "'}' es CODIGO, no texto de la cadena, y sus literales se "
                    "escriben tal cual, sin escapar las comillas: "
                    "f\"{len(\"ab\")}\", no f\"{len(\\\"ab\\\")}\"",
                    line=lx.ln,
                    column=bad_col,
                    file=lx.file,
                )
            if j < 0:
                lx.jump_to(_string_end(src, n, expr_start))
                raise lex_error.InvalidTokenError(
                    "interpolacion sin cerrar: falta '}'",
                    line=lx.ln,
                    column=start_col,
                    file=lx.file,
                )
            raw = src[expr_start:j]
            expr = raw.strip()
            if not expr:
                lx.jump_to(_string_end(src, n, j + 1))
                raise lex_error.InvalidTokenError(
                    "interpolacion vacia: '{}'",
                    line=lx.ln,
                    column=start_col,
                    file=lx.file,
                )
            # la posicion es la del PRIMER caracter de la expresion (sin los
            # espacios de delante): el parser cuenta desde ahi las columnas
            # de cada nodo de la interpolacion
            first = expr_start + (len(raw) - len(raw.lstrip()))
            parts.append(Interp(expr, first - lx._line_start + 1, lx.ln))
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
                lx.jump_to(_char_end(src, n, pos + 1))
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
