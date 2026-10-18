"""Scanner de operadores y delimitadores.

Reconoce simbolos de uno y dos caracteres. Los de dos caracteres
(``==``, ``!=``, ``<=``, ``>=``, ``->``, ``+=``/``-=``/``*=``/``/=``/``%=``,
``++``, ``--``) requieren mirar el siguiente code point antes de decidir el
token, y se prueban ANTES que los de uno.

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
    "%": TokenType.MODULO,
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
    "&": TokenType.ADDRESS,     # prefijo: direccion; infijo: 'y' de bits
    "|": TokenType.PIPE,
    "^": TokenType.CARET,
    "~": TokenType.TILDE,
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
    # AZUCAR: la asignacion compuesta y el incremento son tokens propios pero
    # NO llegan al AST — el parser los desazucara ('n += 2' -> 'n = n + 2').
    # Se reconocen aqui, y no como dos tokens sueltos, porque '+' seguido de
    # '=' tiene que ser UN operador: si no, '+=' parsearia como '+' aplicado a
    # una asignacion y el error no diria nada del operador que se escribio.
    ("+", "="): TokenType.PLUS_ASSIGN,
    ("-", "="): TokenType.MINUS_ASSIGN,
    ("*", "="): TokenType.STAR_ASSIGN,
    ("/", "="): TokenType.SLASH_ASSIGN,
    ("%", "="): TokenType.PERCENT_ASSIGN,
    ("&", "="): TokenType.AMP_ASSIGN,
    ("|", "="): TokenType.PIPE_ASSIGN,
    ("^", "="): TokenType.CARET_ASSIGN,
    ("<", "<"): TokenType.SHIFT_LEFT,
    ("+", "+"): TokenType.INCREMENT,
    ("-", "-"): TokenType.DECREMENT,
}


def scan(lx) -> Token:
    src = lx.source
    pos = lx.pos
    start_col = lx.col
    ch = src[pos]
    nxt = src[pos + 1] if pos + 1 < lx.length else ""

    # '<<=' es el unico de tres caracteres
    if ch == "<" and nxt == "<" and pos + 2 < lx.length and src[pos + 2] == "=":
        lx.jump_to(pos + 3)
        return Token(TokenType.SHIFT_LEFT_ASSIGN, "<<=", "<<=", lx.ln, start_col)

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

    # '!' sin '=' no es un operador valido por si solo: es la negacion de
    # otros lenguajes, y el error dice como se escribe aqui (H06)
    lx.jump_to(pos + 1)
    hint = ("; la negacion logica en suriaX es 'not' ('not b'), y '!=' "
            "compara (distinto)" if ch == "!" else "")
    raise lex_error.UnexpectedCharacterError(
        f"caracter no reconocido: {ch!r}{hint}",
        line=lx.ln,
        column=start_col,
        file=lx.file,
    )
