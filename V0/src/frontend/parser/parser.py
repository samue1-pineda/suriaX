"""Parser de suriaX (esqueleto).

El parser real es de **descenso recursivo + Pratt** y aun NO esta implementado.
Este modulo prepara el contrato para que el parser "no haga mas que recibir los
tokens": expone un cursor sobre la ``list[Token]`` producida por el lexer, con
las primitivas que un parser Pratt necesita (``peek`` / ``advance`` /
``expect``).

La UNICA construccion de tokens implementada aqui es el orquestador de la
directiva ``#test lexer``: cuando el flujo de tokens empieza con la directiva
``test`` seguida del identificador ``lexer``, se vuelca el arreglo de tokens a
consola. Es la via funcional para probar el lexer desde un ``.srcx``.
"""

from __future__ import annotations

from typing import List, Optional

try:
    from include.t_types import Token, TokenType
    from error_handler import ParseError
except ImportError:  # pragma: no cover - ejecucion directa
    from t_types import Token, TokenType  # type: ignore
    import ParseError  # type: ignore


class Parser:
    __slots__ = ("tokens", "pos", "length")

    def __init__(self, tokens: List[Token]):
        # el parser NADA MAS recibe los tokens ya generados por el lexer.
        self.tokens = tokens
        self.length = len(tokens)
        self.pos = 0

    # ------------------------------------------------------------------ #
    # cursor (primitivas para descenso recursivo + Pratt)
    # ------------------------------------------------------------------ #
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
            raise ParseError.ExpectedTokenError(
                f"se esperaba {ttype.name}, se encontro {tok.type.name}",
                line=tok.ln,
                column=tok.col,
            )
        return self.advance()

    # ------------------------------------------------------------------ #
    # orquestador de directivas de prueba  (#test lexer)
    # ------------------------------------------------------------------ #
    def run_test_directive(self) -> Optional[str]:
        """Detecta y ejecuta ``#test <objetivo>`` al inicio del flujo.

        Implementado: ``#test lexer`` -> vuelca el arreglo de tokens a consola.
        Devuelve el objetivo ejecutado (``"lexer"``) o ``None`` si el flujo no
        empieza con una directiva de prueba.
        """
        tok = self.peek()
        if tok.type is not TokenType.DIRECTIVE or tok.value != "test":
            return None

        self.advance()  # consumir la directiva '#test'
        target = self.peek()
        if target.type is TokenType.IDENTIFIER and target.lexeme == "lexer":
            self.advance()
            self._dump_tokens()
            return "lexer"

        # otros objetivos (#test parser, #test hir, ...) aun no implementados
        return None

    def _dump_tokens(self) -> None:
        """Imprime el arreglo completo de tokens via __repr__."""
        print(f"=== #test lexer  ({self.length} tokens) ===")
        for i, tok in enumerate(self.tokens):
            print(f"[{i:>3}] {tok!r}")

    # ------------------------------------------------------------------ #
    # punto de entrada del parser (resto AUN no implementado)
    # ------------------------------------------------------------------ #
    def parse(self):
        """Punto de entrada del parser.

        Por ahora solo atiende la directiva de prueba del lexer. El analisis
        sintactico completo (descenso recursivo + Pratt) se implementara aqui.
        """
        executed = self.run_test_directive()
        if executed is not None:
            return None
        raise NotImplementedError(
            "el parser (descenso recursivo + Pratt) aun no esta implementado"
        )
