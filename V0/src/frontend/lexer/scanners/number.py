"""Scanner de literales numericos (INT_LIT y FLOAT_LIT).

Reconoce:

- enteros y flotantes en base 10 (``42``, ``3.25``);
- enteros en base 16, 2 y 8 con prefijo (``0xFF``, ``0b1010``, ``0o755``),
  como Python;
- ``_`` como separador ENTRE dos digitos (``1_000_000``, ``0xFF_FF``);
- un EXPONENTE decimal (``1e3``, ``2.5e-3``, ``1E+10``): con exponente el
  literal es SIEMPRE ``float``. Uno en base 16, 2 u 8 no lleva exponente
  (``0x1e3`` es el entero hexadecimal ``0x1E3``). Un valor que no cabe en un
  ``float`` (``1e400``) es :class:`NumericLiteralOverflowError` (LEX006), y
  tambien uno distinto de cero tan pequeno que quedaria en ``0.0``
  (``1e-400``): casi seguro es una errata. ``text.parse_float`` en cambio da
  ``0.0``, porque lee datos, no codigo.

Un literal en base 16, 2 u 8 es un PATRON DE BITS (la regla de Java): puede
usar los 64 bits, y si el de arriba esta encendido el valor es negativo
(``0xFFFFFFFFFFFFFFFF`` es ``-1``). Asi se escribe una mascara sin pelear con
el signo. Uno decimal tiene que caber en ``int`` (lo comprueba la Semantica,
que ve el ``-`` de delante).

Un formato invalido produce :class:`InvalidNumberFormatError` (LEX007). El
valor se convierte una sola vez y se guarda ya parseado en el Token; el
lexema conserva lo que se escribio.
"""

from __future__ import annotations

import math

try:
    from include.t_types import Token, TokenType
    from error_handler import lex_error
except ImportError:  # pragma: no cover
    from t_types import Token, TokenType  # type: ignore
    import lex_error  # type: ignore


#: prefijo -> (base, digitos validos, nombre para los mensajes)
_BASES = {
    "x": (16, "0123456789abcdefABCDEF", "hexadecimal"),
    "b": (2, "01", "binario"),
    "o": (8, "01234567", "octal"),
}

_DIEZ = "0123456789"


def _falla(lx, mensaje: str, col: int, hasta: int):
    lx.jump_to(hasta)
    raise lex_error.InvalidNumberFormatError(mensaje, line=lx.ln, column=col,
                                             file=lx.file)


def _fin_del_literal(src: str, pos: int) -> int:
    """Hasta donde llega lo que PARECE un literal (letras, digitos, '_'):
    el error se reporta una vez y el lexer sigue despues."""
    while pos < len(src) and (src[pos].isalnum() or src[pos] == "_"):
        pos += 1
    return pos


def _separador_valido(src: str, pos: int, digitos: str) -> bool:
    """Un '_' vale solo ENTRE dos digitos."""
    return (pos > 0 and src[pos - 1] in digitos
            and pos + 1 < len(src) and src[pos + 1] in digitos)


def _con_base(lx, start: int, start_col: int) -> Token:
    src = lx.source
    base, digitos, nombre = _BASES[src[start + 1].lower()]
    pos = start + 2
    while pos < len(src):
        ch = src[pos]
        if ch in digitos:
            pos += 1
        elif ch == "_":
            if not _separador_valido(src, pos, digitos):
                _falla(lx, "un '_' separa digitos: tiene que ir entre dos",
                       start_col, _fin_del_literal(src, pos))
            pos += 1
        elif ch.isalnum():
            _falla(lx, f"'{ch}' no es un digito {nombre}", start_col,
                   _fin_del_literal(src, pos))
        else:
            break
    lexeme = src[start:pos]
    if pos == start + 2:
        _falla(lx, f"el literal {nombre} no tiene digitos despues de "
                   f"'{lexeme}'", start_col, pos)
    valor = int(lexeme[2:].replace("_", ""), base)
    if valor >= 1 << 64:
        _falla(lx, f"el literal {nombre} '{lexeme}' no cabe en 64 bits",
               start_col, pos)
    if valor >= 1 << 63:
        valor -= 1 << 64          # patron de bits: el bit 63 es el signo
    lx.jump_to(pos)
    return Token(TokenType.INT_LIT, lexeme, valor, lx.ln, start_col)


def scan(lx) -> Token:
    src = lx.source
    n = lx.length
    start = lx.pos
    start_col = lx.col

    if src[start] == "0" and start + 1 < n and src[start + 1] in "xXbBoO":
        return _con_base(lx, start, start_col)

    pos = start
    seen_dot = False

    while pos < n:
        ch = src[pos]
        if "0" <= ch <= "9":   # solo ASCII (ver lexer._dispatch)
            pos += 1
        elif ch == "_":
            if not _separador_valido(src, pos, _DIEZ):
                _falla(lx, "un '_' separa digitos: tiene que ir entre dos",
                       start_col, _fin_del_literal(src, pos))
            pos += 1
        elif ch == ".":
            if seen_dot:
                # segundo punto -> formato invalido
                _falla(lx, "el literal numerico tiene mas de un punto decimal",
                       start_col, pos + 1)
            # un '.' solo es decimal si va seguido de digito; de lo contrario
            # es el operador DOT (p. ej. '1.foo' -> INT '1' y luego '.').
            if pos + 1 < n and "0" <= src[pos + 1] <= "9":
                seen_dot = True
                pos += 1
            else:
                break
        else:
            break

    # exponente: 'e'/'E', signo opcional y digitos. Con exponente el literal
    # es SIEMPRE float ('1e3' es 1000.0), como en C, Java y Python
    has_exponent = False
    if pos < n and src[pos] in "eE":
        k = pos + 1
        if k < n and src[k] in "+-":
            k += 1
        if not (k < n and "0" <= src[k] <= "9"):
            _falla(lx, f"el exponente de '{src[start:k]}' no tiene digitos: "
                       "se escribe '1e3', '2.5e-3' o '1E+10'",
                   start_col, _fin_del_literal(src, k))
        pos = k
        while pos < n:
            ch = src[pos]
            if "0" <= ch <= "9":
                pos += 1
            elif ch == "_":
                if not _separador_valido(src, pos, _DIEZ):
                    _falla(lx, "un '_' separa digitos: tiene que ir entre dos",
                           start_col, _fin_del_literal(src, pos))
                pos += 1
            else:
                break
        has_exponent = True

    lexeme = src[start:pos]
    limpio = lexeme.replace("_", "")

    if seen_dot or has_exponent:
        # el valor es el 'double' mas cercano al decimal escrito: el mismo
        # que da 'text.parse_float' con el mismo texto (float() de Python
        # en el interprete, strtod en la VM)
        valor = float(limpio)
        if math.isinf(valor):
            lx.jump_to(pos)
            raise lex_error.NumericLiteralOverflowError(
                f"el literal '{lexeme}' no cabe en un float (el mayor es "
                "~1.8e308)", line=lx.ln, column=start_col, file=lx.file)
        mantisa = limpio.lower().split("e")[0]
        if valor == 0.0 and any(c in "123456789" for c in mantisa):
            lx.jump_to(pos)
            raise lex_error.NumericLiteralOverflowError(
                f"el literal '{lexeme}' es demasiado pequeno para un float: "
                "quedaria en 0.0 (el menor distinto de cero es ~4.9e-324); "
                "si quieres un cero, escribe 0.0",
                line=lx.ln, column=start_col, file=lx.file)
        lx.jump_to(pos)
        return Token(TokenType.FLOAT_LIT, lexeme, valor, lx.ln, start_col)
    lx.jump_to(pos)
    return Token(TokenType.INT_LIT, lexeme, int(limpio), lx.ln, start_col)
