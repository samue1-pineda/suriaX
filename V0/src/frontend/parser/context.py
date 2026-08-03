"""Estado sintactico compartido entre ``grammar/`` y ``expressions/`` durante el parseo.

Solo contexto **puramente sintactico**: profundidad de bucle (valida la
posicion de ``break``/``continue``), profundidad de region, y decoradores
pendientes antes de una declaracion. La validacion semantica profunda
(propiedad/lifetimes de regiones, resolucion de nombres) NO vive aqui: es
trabajo de la fase de Semantica (Fase 4 del roadmap).
"""

from __future__ import annotations

from typing import Any, List


class ParserContext:
    __slots__ = ("loop_depth", "region_depth", "pending_decorators", "errors",
                 "no_struct_literal")

    def __init__(self) -> None:
        self.loop_depth = 0
        self.region_depth = 0
        self.pending_decorators: List[str] = []
        # errores recuperables acumulados durante el modo panico (ver
        # 'parser/recovery.py'); mismo patron que 'Lexer.errors'.
        self.errors: List[Any] = []
        # posicion donde un '{' que sigue a un nombre abre un BLOQUE, no un
        # literal de struct: el patron de un 'case' ('case Origen { ... }',
        # EBNF 'case_arm'). Sin esto la expresion del patron se come el
        # bloque como 'Origen{...}' y el 'case' siguiente falla pidiendo ':'.
        # Es la misma tecnica que usan los lenguajes con literales de struct
        # y condiciones sin parentesis (Rust: 'no_struct_literal').
        self.no_struct_literal = False

    def enter_loop(self) -> None:
        self.loop_depth += 1

    def exit_loop(self) -> None:
        self.loop_depth -= 1

    def in_loop(self) -> bool:
        return self.loop_depth > 0

    def enter_region(self) -> None:
        self.region_depth += 1

    def exit_region(self) -> None:
        self.region_depth -= 1

    def in_region(self) -> bool:
        return self.region_depth > 0

    def push_decorator(self, name: str) -> None:
        self.pending_decorators.append(name)

    def drain_decorators(self) -> List[str]:
        """Consume y devuelve los decoradores acumulados antes de una declaracion."""
        pending = self.pending_decorators
        self.pending_decorators = []
        return pending
