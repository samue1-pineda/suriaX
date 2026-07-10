"""Scanner de literales numericos (INT_LIT y FLOAT_LIT).

Reconoce enteros y flotantes en base 10. Un unico punto decimal produce un
FLOAT_LIT; multiples puntos o un formato invalido producen
:class:`InvalidNumberFormatError` (LEX007).

El valor se convierte una sola vez (``int`` / ``float``) y se guarda ya
parseado en el Token, evitando reconvertir en fases posteriores.
"""

from __future__ import annotations

try:
    from include.t_types import Token, TokenType
    from error_handler import lex_error
except ImportError:  # pragma: no cover
    from t_types import Token, TokenType  # type: ignore
    import lex_error  # type: ignore


def scan(lx) -> Token:
    src = lx.source
    n = lx.length
    start = lx.pos
    start_col = lx.col

    pos = start
    seen_dot = False

    while pos < n:
        ch = src[pos]
        if ch.isdigit():
            pos += 1
        elif ch == ".":
            if seen_dot:
                # segundo punto -> formato invalido
                lx.jump_to(pos + 1)
                raise lex_error.InvalidNumberFormatError(
                    "el literal numerico tiene mas de un punto decimal",
                    line=lx.ln,
                    column=start_col,
                    file=lx.file,
                )
            # un '.' solo es decimal si va seguido de digito; de lo contrario
            # es el operador DOT (p. ej. '1.foo' -> INT '1' y luego '.').
            if pos + 1 < n and src[pos + 1].isdigit():
                seen_dot = True
                pos += 1
            else:
                break
        else:
            break

    lexeme = src[start:pos]
    lx.jump_to(pos)

    if seen_dot:
        return Token(TokenType.FLOAT_LIT, lexeme, float(lexeme), lx.ln, start_col)
    return Token(TokenType.INT_LIT, lexeme, int(lexeme), lx.ln, start_col)
