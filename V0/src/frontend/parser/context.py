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
                 "no_struct_literal", "finally_loops", "with_receivers",
                 "with_count", "in_test", "expects", "in_call_args",
                 "args_hint", "lambda_hides_loop", "lambda_hides_test")

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
        # la profundidad de bucle al ENTRAR a cada 'finally' que se esta
        # leyendo: un 'break' que salga de un bucle de afuera abandonaria el
        # 'finally' a medias (PAR027); uno de un bucle de adentro, no.
        self.finally_loops: List[int] = []
        # el receptor de '.campo' de cada 'with' abierto (None = el 'with'
        # tiene varios valores y '.campo' no diria de cual); y cuantos
        # guardianes sin nombre van, para darles uno que nadie puede escribir
        self.with_receivers: List[Any] = []
        self.with_count = 0
        # dentro del CUERPO de un 'test' (donde vale 'expect') y cuantos
        # 'expect' lleva: una prueba sin ninguno no comprueba nada (PAR029)
        self.in_test = False
        self.expects = 0
        # leyendo DIRECTAMENTE los argumentos de una llamada (sin otro
        # delimitador por medio): ahi 'a < b, c > (d)' tambien podria ser
        # dos comparaciones; y la explicacion de esa ambiguedad, si aparecio
        # entre los argumentos que se estan leyendo (la recibe la llamada de
        # fuera, ver 'expressions/nud._parse_arg_list')
        self.in_call_args = False
        self.args_hint = ""
        # dentro de una LAMBDA que esta, a su vez, dentro de un bucle o de un
        # 'test': la lambda es una funcion aparte y los corta, asi que un
        # 'break'/'continue'/'expect' de su cuerpo no llega a ellos. Solo
        # cambia el MENSAJE del PAR013, que antes decia "fuera de un bucle"
        # con el 'break' escrito dentro de un 'while' (A03).
        self.lambda_hides_loop = False
        self.lambda_hides_test = False

    def in_finally(self) -> bool:
        return bool(self.finally_loops)

    def jump_leaves_finally(self) -> bool:
        """¿Un 'break'/'continue' aqui saltaria FUERA del 'finally'?"""
        return bool(self.finally_loops) and self.loop_depth == self.finally_loops[-1]

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
