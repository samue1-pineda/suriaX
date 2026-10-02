"""Parser de suriaX: orquestador.

Coordina el ``Cursor`` (``cursor.py``) y el ``ParserContext``
(``context.py``) para invocar el punto de entrada gramatical
(``grammar/program.py``), que combina descenso recursivo LL(k) para
sentencias/declaraciones con el motor Pratt (``pratt.py``) para expresiones.

Tambien atiende las directivas de prueba orquestadas por ``#test``:

 - ``#test lexer``  -> vuelca el arreglo de tokens a consola (sin parsear).
 - ``#test parser``  -> parsea y vuelca el AST en JSON.
 - ``#test ast``     -> parsea, resuelve tipos explicitos (AST-tipado, ver
   ``typed_ast.py``) y vuelca el resultado en JSON.
 - ``#test sem``     -> parsea y corre la fase Semantica
   (``src/frontend/semantic/``), vuelca la tabla de simbolos en JSON. El
   import de ``semantic`` es DIFERIDO (dentro del metodo): el paquete
   ``parser`` no debe depender de ``semantic`` en tiempo de carga -- son
   fases separadas, la dependencia es solo de esta directiva de depuracion.
 - ``#test hir``     -> pipeline completo + emision del HIR en el formato de
   TEXTO de protobuf (``src/HIR/emmit_IR.py``, import igual de diferido:
   requiere la dependencia ``protobuf`` solo si se usa).

Estas directivas son un atajo de depuracion (ver ROADMAP.md, Fase 2); el
punto de entrada real para el resto del compilador es :meth:`Parser.parse`.
"""

from __future__ import annotations

import sys
from typing import List, Optional

try:
    from include import ast_nodes as ast
    from include.ast_json import to_json
    from include.t_types import Token, TokenType
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from include.ast_json import to_json  # type: ignore
    from t_types import Token, TokenType  # type: ignore

from .context import ParserContext
from .cursor import Cursor
from .grammar.program import parse_program
from .typed_ast import resolve_types


class Parser:
    __slots__ = ("tokens", "cursor", "ctx", "fuente")

    def __init__(self, tokens: List[Token]):
        # el parser NADA MAS recibe los tokens ya generados por el lexer.
        self.tokens = tokens
        self.cursor = Cursor(tokens)
        self.ctx = ParserContext()
        # el TEXTO del fuente, si quien lo corre lo tiene (solo para citarlo
        # en la vista de desugaring; el parser no lo usa)
        self.fuente: Optional[str] = None

    # ------------------------------------------------------------------ #
    # punto de entrada real del parser
    # ------------------------------------------------------------------ #
    def parse(self) -> ast.Program:
        """Analiza el flujo completo segun la gramatica y devuelve el AST.

        Nunca lanza por errores de sintaxis: se recuperan en modo panico y
        quedan acumulados en ``self.ctx.errors`` (mismo patron que
        ``Lexer.errors``); el AST devuelto es el mejor esfuerzo posible.
        """
        return parse_program(self.cursor, self.ctx)

    # ------------------------------------------------------------------ #
    # orquestador de directivas de prueba (#test lexer/parser/ast)
    # ------------------------------------------------------------------ #
    def consume_test_directive(self) -> Optional[str]:
        """Consume ``#test <objetivo>`` al inicio del flujo y devuelve el objetivo.

        SOLO consume: no ejecuta nada ni imprime nada. Separarlo de
        ``run_test_directive`` es lo que permite que un consumidor que unicamente
        quiere PARSEAR el archivo -- el canal de diagnosticos del LSP, ver
        ``driver/inspect.py:emit_diagnostics`` -- salte la directiva igual que hace la
        ruta normal, sin disparar el volcado de una fase.

        Sin esa separacion ``#test`` llegaba a ``parse_directive``, que no tiene
        rama para el, y un archivo VALIDO se reportaba con ``PAR020`` (y, por la
        recuperacion en modo panico, con errores semanticos inventados detras).

        Devuelve el nombre del objetivo (tal cual se escribio) o ``None`` si el
        flujo no empieza por una directiva de prueba.
        """
        tok = self.cursor.peek()
        if tok.type is not TokenType.DIRECTIVE or tok.value != "test":
            return None

        # Mirar el token siguiente SIN consumir la directiva todavia: si no hay
        # objetivo, '#test' no es una directiva de prueba y el flujo debe quedar
        # intacto para que el parser lo reporte como corresponde.
        target = self.cursor.peek(1)
        if target.type is not TokenType.IDENTIFIER:
            return None

        self.cursor.advance()  # '#test'
        self.cursor.advance()  # el objetivo
        return target.lexeme

    def run_test_directive(self, *, source_path: Optional[str] = None) -> Optional[str]:
        """Detecta y ejecuta ``#test <objetivo>`` al inicio del flujo.

        Implementado: ``lexer`` (tokens), ``parser`` (AST en JSON), ``ast``
        (AST-tipado en JSON), ``sem`` (tabla de simbolos en JSON). Devuelve
        el objetivo ejecutado o ``None`` si el flujo no empieza con una
        directiva de prueba reconocida. ``source_path`` (ruta del archivo
        fuente) ancla la resolucion de ``.libsrx`` en ``#test sem``.
        """
        target = self.consume_test_directive()
        if target is None:
            return None

        # matching CASE-INSENSITIVE ('#test HIR' == '#test hir'): cada fase
        # ejecuta sus prerequisitos internamente (hir corre lexer -> parser
        # -> AST-tipado -> Semantica); el usuario solo nombra la que quiere
        # ver. Un objetivo desconocido se reporta con la lista disponible en
        # vez de caer al pipeline normal (que intentaria parsear '#test X'
        # como codigo y daria un PAR003 confuso).
        handler = self._TEST_TARGETS.get(target.lower())
        if handler is None:
            available = ", ".join(sorted(self._TEST_TARGETS))
            print(f"=== #test {target} — objetivo desconocido ===",
                  file=sys.stderr)
            print(f"  fases disponibles: {available}", file=sys.stderr)
            return "unknown"
        return handler(self, source_path)

    # tabla de despacho de '#test <fase>': nombre (minusculas) -> metodo.
    # Agregar una fase nueva es agregar una entrada aqui (mismo patron que
    # PRIMARY_HANDLERS del parser); el nombre devuelto es el ejecutado.
    def _run_test_lexer(self, source_path: Optional[str]) -> str:
        self._dump_tokens()
        return "lexer"

    def _run_test_parser(self, source_path: Optional[str]) -> str:
        self._dump_json("parser", self.parse())
        return "parser"

    def _run_test_ast(self, source_path: Optional[str]) -> str:
        program = self.parse()
        resolve_types(program)
        self._dump_json("ast", program)
        return "ast"

    def _run_test_sem(self, source_path: Optional[str]) -> str:
        program = self.parse()
        resolve_types(program)
        from ..semantic import analyze  # import diferido, ver docstring del modulo
        table, sem_errors = analyze(program, source_path=source_path)
        self._dump_sem(table, sem_errors)
        return "sem"

    def _run_test_hir(self, source_path: Optional[str]) -> str:
        program = self.parse()
        resolve_types(program)
        from ..semantic import analyze  # import diferido, ver docstring del modulo
        table, sem_errors = analyze(program, source_path=source_path)
        self._dump_hir(program, table, sem_errors, source_path=source_path)
        return "hir"

    def _run_test_desugar(self, source_path: Optional[str]) -> str:
        """Lo que se escribio y lo que el compilador entiende: el HIR legible
        con cada construccion que salio de un azucar marcada, y la linea del
        fuente encima (ver ``src/HIR/desugar.py``)."""
        program = self.parse()
        resolve_types(program)
        from ..semantic import analyze  # import diferido, ver docstring del modulo
        table, sem_errors = analyze(program, source_path=source_path)
        if self.ctx.errors or sem_errors:
            print("=== #test desugar — NO emitido: hay errores previos ===")
            for err in (*self.ctx.errors, *sem_errors):
                print(f"  {err.code}: {err.message}  ({err.loc})")
            return "desugar"
        fuente = self.fuente
        if fuente is None and source_path:
            try:
                with open(source_path, encoding="utf-8") as fh:
                    fuente = fh.read()
            except OSError:
                fuente = None
        from src.HIR.desugar import render  # import diferido (protobuf)
        texto, errores = render(program, table, source_file=source_path or "",
                               source=fuente)
        if texto is None:
            print(f"=== #test desugar — NO emitido ({len(errores)} errores) ===")
            for err in errores:
                print(f"  {err.code}: {err.message}  ({err.loc})")
            return "desugar"
        print(texto)
        return "desugar"

    def run_stage(self, name: str, *, source_path: Optional[str] = None) -> Optional[str]:
        """Ejecuta el volcado de UNA fase, sin que el fuente traiga '#test'.

        Misma tabla de despacho que ``#test <fase>`` -- una fase nueva sigue
        siendo una entrada en ``_TEST_TARGETS`` y nada mas. Lo que cambia es
        quien la pide: la directiva la pide DESDE el archivo, y esto la pide
        desde fuera, que es lo que necesita un visualizador para mostrar
        cualquier fase de un archivo que el usuario no quiere modificar.

        Devuelve la fase ejecutada, o ``None`` si el nombre no existe.
        """
        handler = self._TEST_TARGETS.get(name.lower())
        if handler is None:
            return None
        return handler(self, source_path)

    @classmethod
    def available_stages(cls) -> list:
        """Nombres de fase que ``run_stage`` acepta, en orden de pipeline."""
        return list(cls._TEST_TARGETS)

    _TEST_TARGETS = {
        "lexer": _run_test_lexer,
        "parser": _run_test_parser,
        "ast": _run_test_ast,
        "sem": _run_test_sem,
        "hir": _run_test_hir,
        "desugar": _run_test_desugar,
    }

    def _dump_tokens(self) -> None:
        """Imprime el arreglo completo de tokens via __repr__."""
        print(f"=== #test lexer  ({len(self.tokens)} tokens) ===")
        for i, tok in enumerate(self.tokens):
            print(f"[{i:>3}] {tok!r}")

    def _dump_json(self, target: str, program: ast.Program) -> None:
        """Imprime el AST (o AST-tipado) resultante en formato JSON."""
        print(f"=== #test {target}  ({len(program.items)} items de nivel superior) ===")
        print(to_json(program))
        if self.ctx.errors:
            print(f"\n=== errores de sintaxis ({len(self.ctx.errors)}) ===")
            for err in self.ctx.errors:
                print(f"  {err.code}: {err.message}  ({err.loc})")

    def _dump_hir(self, program: ast.Program, table, sem_errors: List,
                  *, source_path: Optional[str]) -> None:
        """Imprime el HIR en el formato de TEXTO de protobuf (educativo,
        mismo objetivo que ``#test sem``); el binario real lo escribe
        ``--emit-hir`` (``V0/main.py``). Con errores previos (sintaxis o
        semántica) el HIR NO se emite: la frontera no se cruza con un
        programa inválido."""
        if self.ctx.errors or sem_errors:
            print("=== #test hir — NO emitido: hay errores previos ===")
            for err in (*self.ctx.errors, *sem_errors):
                print(f"  {err.code}: {err.message}  ({err.loc})")
            return
        from src.HIR.emmit_IR import emit_text  # import diferido (protobuf)
        text, hir_errors = emit_text(program, table,
                                     source_file=source_path or "")
        if hir_errors:
            print(f"=== #test hir — NO emitido ({len(hir_errors)} errores) ===")
            for err in hir_errors:
                print(f"  {err.code}: {err.message}  ({err.loc})")
            return
        print(f"=== #test hir  ({len(program.items)} items de nivel superior) ===")
        print(text)

    def _dump_sem(self, table, sem_errors: List) -> None:
        """Imprime la tabla de simbolos (scope global + hooks) en formato JSON."""
        from ..semantic.symbol_table import to_debug_dict
        n_syms = len(table.global_scope.values) + len(table.global_scope.types)
        print(f"=== #test sem  ({n_syms} simbolos globales, {len(table.hooks)} hooks) ===")
        print(to_json(to_debug_dict(table)))
        if self.ctx.errors:
            print(f"\n=== errores de sintaxis ({len(self.ctx.errors)}) ===")
            for err in self.ctx.errors:
                print(f"  {err.code}: {err.message}  ({err.loc})")
        if sem_errors:
            print(f"\n=== errores semanticos ({len(sem_errors)}) ===")
            for err in sem_errors:
                print(f"  {err.code}: {err.message}  ({err.loc})")


__all__ = ["Parser"]
