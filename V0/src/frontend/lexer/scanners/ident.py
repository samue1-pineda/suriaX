"""Scanner de identificadores, palabras reservadas y "dunder" (``__foo__``).

Reconoce un identificador segun las reglas Unicode del lenguaje
(``XID_Start`` / ``XID_Continue``) y, con una unica busqueda en la tabla
:data:`include.t_types.KEYWORDS`, decide si es una palabra reservada o un
``IDENTIFIER`` de usuario.

Un identificador con la FORMA ``__x__`` (empieza y termina en ``__``, con al
menos un caracter dentro) se reconoce como ``DUNDER`` en vez de
``IDENTIFIER``. El lexer es deliberadamente **permisivo**: reconoce la forma
para CUALQUIER nombre, sin validar contra una lista cerrada (a diferencia de
``DIRECTIVES`` en ``c_dir.py``). El significado de cada nombre concreto
(``free``/``make``/``sizeof`` como *hooks* de tipo, u otros a futuro) lo
decide la fase Semantica -- anadir un hook nuevo no vuelve a tocar el lexer
(ver ``semantic/hooks.py`` y ``DESIGN_PRINCIPLES.md`` secc. 2: "anadir
capacidades rara vez implica anadir tokens"). ``Token.value`` para un
``DUNDER`` es el nombre YA SIN los guiones (``"free"`` para ``__free__``).

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

    if len(lexeme) > 4 and lexeme.startswith("__") and lexeme.endswith("__"):
        return Token(TokenType.DUNDER, lexeme, lexeme[2:-2], lx.ln, start_col)

    ttype = KEYWORDS.get(lexeme, TokenType.IDENTIFIER)
    return Token(ttype, lexeme, lexeme, lx.ln, start_col)
