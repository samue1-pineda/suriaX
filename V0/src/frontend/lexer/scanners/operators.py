"""Scanner de operadores y delimitadores.

Reconoce simbolos de uno y dos caracteres. Los de dos caracteres
(``==``, ``!=``, ``<=``, ``>=``, ``->``) requieren mirar el siguiente code point
antes de decidir el token.

Los comentarios (``//``, ``/- -/``) NO se manejan aqui: el dispatcher del
lexer los intercepta antes de llegar a este scanner (ver ``lexer.py``).
"""

from __future__ import annotations

try:
    from include.t_types import Token, TokenType
    from error_handler import lex_error
except ImportError:  # pragma: no cover
    from t_types import Token, TokenType  # type: ignore
    import lex_error  # type: ignore


# simbolos de un solo caracter -> TokenType
_SINGLE = {
    "+": TokenType.PLUS,
    "-": TokenType.MINUS,
    "*": TokenType.MULTIPLY,
    "/": TokenType.DIVIDE,
    "(": TokenType.L_PAREN,
    ")": TokenType.R_PAREN,
    "{": TokenType.L_BRACE,
    "}": TokenType.R_BRACE,
    "[": TokenType.L_BRACKET,
    "]": TokenType.R_BRACKET,
    ".": TokenType.DOT,
    ",": TokenType.COMMA,
    ";": TokenType.SEMICOLON,
    ":": TokenType.COLON,
    "&": TokenType.ADDRESS,
    "?": TokenType.NULLABLE,
    "=": TokenType.ASSIGN,
    "<": TokenType.LESS,
    ">": TokenType.GREATER,
}

# (caracter, siguiente) -> TokenType para simbolos de dos caracteres.
_DOUBLE = {
    ("=", "="): TokenType.EQUAL,
    ("!", "="): TokenType.NOT_EQUAL,
    ("<", "="): TokenType.LESS_EQUAL,
    (">", "="): TokenType.GREATER_EQUAL,
    ("-", ">"): TokenType.ARROW,     # -> (tipo de retorno de funcion)
}


def scan(lx) -> Token:
    src = lx.source
    pos = lx.pos
    start_col = lx.col
    ch = src[pos]
    nxt = src[pos + 1] if pos + 1 < lx.length else ""

    # intentar primero el operador de dos caracteres
    two = _DOUBLE.get((ch, nxt))
    if two is not None:
        lexeme = ch + nxt
        lx.jump_to(pos + 2)
        return Token(two, lexeme, lexeme, lx.ln, start_col)

    single = _SINGLE.get(ch)
    if single is not None:
        lx.jump_to(pos + 1)
        return Token(single, ch, ch, lx.ln, start_col)

    # '!' sin '=' no es un operador valido por si solo
    lx.jump_to(pos + 1)
    raise lex_error.UnexpectedCharacterError(
        f"caracter no reconocido: {ch!r}",
        line=lx.ln,
        column=start_col,
        file=lx.file,
    )
