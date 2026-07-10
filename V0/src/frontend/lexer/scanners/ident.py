"""Scanner de identificadores y palabras reservadas.

Reconoce un identificador segun las reglas Unicode del lenguaje
(``XID_Start`` / ``XID_Continue``) y, con una unica busqueda en la tabla
:data:`include.t_types.KEYWORDS`, decide si es una palabra reservada o un
``IDENTIFIER`` de usuario.

Recibe el objeto ``Lexer`` (estado compartido) y avanza sobre el.
"""

from __future__ import annotations

try:
    from include.t_types import KEYWORDS, Token, TokenType
except ImportError:  # pragma: no cover
    from t_types import KEYWORDS, Token, TokenType  # type: ignore


def is_ident_start(ch: str) -> bool:
    """Caracter valido para INICIAR un identificador (XID_Start o '_')."""
    return ch == "_" or ch.isidentifier()


def is_ident_continue(ch: str) -> bool:
    """Caracter valido para CONTINUAR un identificador (XID_Continue)."""
    # ('a' + ch).isidentifier() captura XID_Continue sin tablas propias.
    return ch == "_" or ch.isalnum() or ("a" + ch).isidentifier()


def scan(lx) -> Token:
    src = lx.source
    n = lx.length
    start = lx.pos
    start_col = lx.col

    pos = start + 1  # el primer caracter ya fue validado por el dispatcher
    while pos < n:
        ch = src[pos]
        if ch == "_" or ch.isalnum() or ("a" + ch).isidentifier():
            pos += 1
        else:
            break

    lexeme = src[start:pos]
    lx.jump_to(pos)

    ttype = KEYWORDS.get(lexeme, TokenType.IDENTIFIER)
    return Token(ttype, lexeme, lexeme, lx.ln, start_col)
