"""Cursor sobre ``list[Token]``: unico punto de acceso a la secuencia de tokens.

Aislar el cursor del resto del parser permite que tanto la capa LL(k)
(``grammar/``) como el motor Pratt (``pratt.py``) compartan un unico recorrido
lineal, sin copias del arreglo de tokens ni estados divergentes.
"""

from __future__ import annotations

from typing import Collection, List

try:
    from include.t_types import KEYWORDS, Token, TokenType
    from error_handler import ParseError
except ImportError:  # pragma: no cover - ejecucion directa
    from t_types import KEYWORDS, Token, TokenType  # type: ignore
    import ParseError  # type: ignore


class Cursor:
    __slots__ = ("tokens", "pos", "length")

    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.length = len(tokens)
        self.pos = 0

    def peek(self, offset: int = 0) -> Token:
        """Token en la posicion actual (+offset) sin consumirlo."""
        i = self.pos + offset
        if i < self.length:
            return self.tokens[i]
        return self.tokens[-1]  # siempre es EOF

    def advance(self) -> Token:
        """Devuelve el token actual y avanza el cursor."""
        tok = self.peek()
        if tok.type is not TokenType.EOF:
            self.pos += 1
        return tok

    def check(self, ttype: TokenType) -> bool:
        """¿El token actual es del tipo dado?"""
        return self.peek().type is ttype

    def check_any(self, ttypes: Collection[TokenType]) -> bool:
        """¿El token actual pertenece al conjunto dado? (uso con FIRST/SYNC sets)."""
        return self.peek().type in ttypes

    def match(self, ttype: TokenType) -> bool:
        """Consume el token actual si coincide; devuelve si lo hizo."""
        if self.check(ttype):
            self.advance()
            return True
        return False

    def expect(self, ttype: TokenType) -> Token:
        """Consume el token actual exigiendo un tipo; si no, lanza ParseError."""
        tok = self.peek()
        if tok.type is not ttype:
            if ttype is TokenType.IDENTIFIER and is_reserved_word(tok):
                raise reserved_word_error(tok)
            raise ParseError.ExpectedTokenError(
                f"se esperaba {ttype.name}, se encontro {tok.type.name}",
                line=tok.ln,
                column=tok.col,
            )
        return self.advance()

    def expect_name(self) -> Token:
        """Consume un "nombre": ``IDENTIFIER`` o ``DUNDER``.

        ``DUNDER`` es gramaticalmente un ``IDENTIFIER`` (la forma ``__x__``
        solo importa para la fase Semantica, ver ``semantic/hooks.py``): debe
        aceptarse en TODA posicion donde el usuario declara o referencia un
        nombre (struct, campo, enum/item, parametro, variable, region,
        member access, alias de import...). Usar ``expect(IDENTIFIER)``
        directamente en una posicion de nombre es un bug -- ver
        ``parser/ARQUITECTURA.md`` (hallazgo de revision de calidad: DUNDER
        solo se aceptaba en la posicion de nombre de funcion, rompiendo
        ``fn __free__(T ptr __self__)`` o ``x.__free__()``).
        """
        tok = self.peek()
        if tok.type is TokenType.IDENTIFIER or tok.type is TokenType.DUNDER:
            return self.advance()
        if is_reserved_word(tok):
            raise reserved_word_error(tok)
        raise ParseError.ExpectedTokenError(
            f"se esperaba un nombre (IDENTIFIER o DUNDER), se encontro {tok.type.name}",
            line=tok.ln,
            column=tok.col,
        )

    def at_end(self) -> bool:
        return self.peek().type is TokenType.EOF


def is_reserved_word(tok: Token) -> bool:
    """¿El token es una palabra reservada (``error``, ``if``, ``type``...)?"""
    return KEYWORDS.get(tok.lexeme) is tok.type


def reserved_word_error(tok: Token) -> ParseError.ParseError:
    """Una palabra reservada donde va un NOMBRE: el mensaje lo dice.

    Antes salia ``se esperaba un nombre ..., se encontro ERRORTYPE``: el
    nombre interno del token, que no dice que ``error`` sea una palabra del
    lenguaje (es el tipo de los valores que pueden fallar). El codigo sigue
    siendo ``PAR003`` (falta un token concreto: el nombre)."""
    return ParseError.ExpectedTokenError(
        f"'{tok.lexeme}' es una palabra reservada del lenguaje y no puede "
        f"usarse como nombre; elige otro (p. ej. '{tok.lexeme}_' o "
        f"'mi_{tok.lexeme}')",
        line=tok.ln,
        column=tok.col,
    )
