"""Lexer de suriaX: modulo padre que orquesta los scanners.

Diseño (rendimiento + modularidad):

 - **estado compartido**: el ``Lexer`` mantiene ``source`` (ya decodificado a
   Unicode por ``source_reader``), ``pos``, ``ln`` y el inicio de la linea
   actual. La columna se calcula bajo demanda (``col``), evitando actualizarla
   en cada caracter.
 - **dispatch por tabla**: el primer code point de cada token decide, en O(1),
   que scanner se invoca. Los scanners reciben este objeto y avanzan sobre el
   mediante :meth:`jump_to`.
 - **comentarios en el mismo paso**: ``//`` y ``/- -/`` se saltan dentro del
   bucle principal, sin segunda pasada ni copia del texto.
 - **salida**: ``tokenize()`` devuelve una ``list[Token]`` terminada en un
   token ``EOF``. Es lo unico que el parser recibe.
"""

from __future__ import annotations

from typing import List, Optional

try:
    from include.t_types import Token, TokenType
    from error_handler import lex_error
    from error_handler.error import CompilerError
except ImportError:  # pragma: no cover - ejecucion directa
    from t_types import Token, TokenType  # type: ignore
    import lex_error  # type: ignore
    from error import CompilerError  # type: ignore

from .scanners import c_dir, ident, number, operators, strings


class Lexer:
    __slots__ = (
        "source",
        "file",
        "length",
        "pos",
        "ln",
        "_line_start",
        "tokens",
        "errors",
    )

    def __init__(self, source: str, *, file: Optional[str] = None):
        self.source = source
        self.file = file
        self.length = len(source)
        self.pos = 0
        self.ln = 1
        self._line_start = 0
        self.tokens: List[Token] = []
        # erroes recuperables acumulados; se reportan al final.
        self.errors: List[CompilerError] = []

    @property
    def col(self) -> int:
        """Columna 1-based de la posicion actual."""
        return self.pos - self._line_start + 1

    def jump_to(self, new_pos: int) -> None:
        """Avanza la posicion a ``new_pos`` actualizando linea/columna.

        Recorre solo el tramo saltado en busca de ``\\n``. Como cada caracter
        del fuente se cruza a lo sumo una vez en total, el coste global del
        lexer se mantiene lineal.
        """
        src = self.source
        i = self.pos
        ln = self.ln
        line_start = self._line_start
        while i < new_pos:
            if src[i] == "\n":
                ln += 1
                line_start = i + 1
            i += 1
        self.pos = new_pos
        self.ln = ln
        self._line_start = line_start

    # ------------------------------------------------------------------ #
    # bucle principal
    # ------------------------------------------------------------------ #
    def tokenize(self) -> List[Token]:
        """Tokeniza todo el fuente y devuelve la lista terminada en EOF."""
        src = self.source
        n = self.length

        while self.pos < n:
            ch = src[self.pos]

            # 1. espacios en blanco (incluye '\n')
            if ch.isspace():
                self.jump_to(self._skip_whitespace())
                continue

            # 2. comentarios: '//' y '/- -/'
            if ch == "/" and self.pos + 1 < n:
                nxt = src[self.pos + 1]
                if nxt == "/":
                    c_dir.skip_line_comment(self)
                    continue
                if nxt == "-":
                    self._guard(c_dir.skip_block_comment)
                    continue

            # 3. dispatch por clase de caracter
            tok = self._dispatch(ch)
            if tok is not None:
                # Dos literales de cadena ADYACENTES son uno solo (como en C,
                # C++ y Python). Se funden aqui, en O(1) por token y sin
                # relectura: entre dos tokens solo hubo espacios o comentarios,
                # que el bucle ya se saltó, así que ser vecinos en la lista es
                # exactamente ser adyacentes en el fuente.
                if (tok.type is TokenType.STRING_LIT and self.tokens
                        and self.tokens[-1].type is TokenType.STRING_LIT):
                    self.tokens[-1] = strings.join_adjacent(self.tokens[-1], tok)
                else:
                    self.tokens.append(tok)

        eof_col = self.col
        self.tokens.append(Token(TokenType.EOF, "", None, self.ln, eof_col))
        return self.tokens

    def _dispatch(self, ch: str) -> Optional[Token]:
        # f-string: prefijo 'f' pegado a '"' (la interpolacion es OPT-IN;
        # una cadena plana no interpola, ver scanners/strings.py). El costo
        # es una comparacion extra SOLO cuando el token empieza por 'f'.
        if (
            ch == "f"
            and self.pos + 1 < self.length
            and self.source[self.pos + 1] == '"'
        ):
            return self._guard(strings.scan_fstring)
        # identificadores / palabras reservadas
        if ch == "_" or ch.isidentifier():
            return self._guard(ident.scan)
        # numeros
        if ch.isdigit():
            return self._guard(number.scan)
        # cadenas / caracteres
        if ch == '"':
            return self._guard(strings.scan_string)
        if ch == "'":
            return self._guard(strings.scan_char)
        # directivas
        if ch == "#":
            return self._guard(c_dir.scan_directive)
        # decoradores
        if ch == "@":
            return self._guard(c_dir.scan_decorator)
        # operadores y delimitadores
        return self._guard(operators.scan)

    def _guard(self, fn):
        start = self.pos #posicion inicial
        start_col = self.col #columna inicial
        start_ln = self.ln #linea inicial
        try:
            return fn(self)
        except lex_error.LexError as exc:
            self.errors.append(exc)
            if self.pos == start:  # garantia anti-bucle
                self.jump_to(start + 1)
            lexeme = self.source[start:self.pos]
            return Token(TokenType.ERROR, lexeme, exc.code, start_ln, start_col)

    def _skip_whitespace(self) -> int:
        src = self.source #codigo fuente
        n = self.length #largo del codigo 
        pos = self.pos #posicion 
        while pos < n and src[pos].isspace():
            pos += 1
        return pos


def tokenize(source: str, *, file: Optional[str] = None) -> List[Token]:
    """Atajo funcional: crea un Lexer y devuelve la lista de tokens."""
    return Lexer(source, file=file).tokenize()
