"""ORQUESTADOR del intérprete: monta la imagen y ejecuta la entrada (secc. 4).

``run(image, config)``:

 1. construye el frame GLOBAL de cada unidad (funciones, enums e items,
    metatipos) — libs primero, main al final;
 2. ejecuta los statements de nivel de módulo de cada unidad en orden de
    declaración (bindings de imports, variables globales);
 3. localiza la función de entrada (``interpreter.entry`` del yaml,
    ``main`` por defecto) en el módulo principal y la llama;
 4. devuelve el exit code (retorno ``int`` de la entrada, o 0).

Flujo unidireccional ``loader -> interpreter -> evaluator``: este módulo no
conoce la CLI ni ``config/`` (recibe el dict ya cargado).
"""

from __future__ import annotations

from typing import Any, Optional

from .enviroment.environment import Frame
from .errors import MissingEntryError, SuriaXRuntimeError
from .evaluator import Evaluator, Thrown
from .loader import Image, Unit
from .memory.pointer import Cell
from .values import EnumNamespace, FunctionValue, Namespace, TypeValue, format_value


def _build_globals(unit: Unit) -> Frame:
    """Frame global de una unidad: todo lo resoluble SIN ejecutar."""
    frame = Frame()
    for name, decl in unit.functions.items():
        frame.define(name, Cell(FunctionValue(unit.alias, decl), name=name))
    for enum_name, items in unit.enum_values.items():
        frame.define(enum_name, Cell(EnumNamespace(enum_name, items),
                                     name=enum_name))
        for item_name, value in items.items():
            # los items tambien resuelven PELADOS ('case Rojo:'), igual que
            # en la tabla de simbolos (namespace de valores).
            frame.define(item_name, Cell(value, name=item_name))
    return frame


def _run_module_level(unit: Unit, evaluator: Evaluator) -> None:
    """Statements sueltos a nivel de módulo, en orden de declaración."""
    for decl in unit.module.items:
        which = decl.WhichOneof("node")
        if which == "statement":
            evaluator.exec_stmt(decl.statement, unit.globals_frame)
        elif which == "import_directive":
            # el HIR trae la resolución YA hecha por la Semántica (D3): el
            # nombre local ('binding') y la unidad calificada ('unit') que
            # hay que ligar. Los fallbacks cubren un .phir de antes de que
            # esos campos existieran, no una decisión del intérprete.
            d = decl.import_directive
            name = d.binding or d.alias or d.lib
            target_unit = d.unit or d.lib
            unit.globals_frame.define(
                name, Cell(Namespace(target_unit), name=name))
        elif which == "from_directive":
            d = decl.from_directive
            name = d.alias or d.name
            target = evaluator._namespace_member(  # miembro real de la unidad
                Namespace(d.unit or d.lib), d.name, ln=decl.ln, col=decl.col,
            )
            unit.globals_frame.define(name, Cell(target, name=name))
        # function/struct/enum/extern/export: ya indexados o sin efecto aqui


def run(image: Image, config: Optional[dict] = None,
        events: Optional[list] = None) -> int:
    """Ejecuta la imagen. Los errores de runtime (``RTxxx``) se reportan a
    stderr con su posición y devuelven exit code 70 (EX_SOFTWARE).

    ``events``: lista donde ACUMULAR la traza en vez de imprimirla (la usa
    ``--debug`` para volcarla al reporte); ``None`` = traza a consola."""
    import sys

    # recicla el backend de memoria (nativo o Python) al empezar cada run: los
    # handles son monotonicos DENTRO de un run; entre runs del mismo proceso se
    # reinician para no acumular celdas de ejecuciones previas.
    from .memory import native
    if native.AVAILABLE:
        native.reset()

    interp_cfg = ((config or {}).get("interpreter") or {})
    entry_name = interp_cfg.get("entry", "main")
    evaluator = Evaluator(
        image,
        trace=bool(interp_cfg.get("trace_memory", False)),
        trace_exec=bool(interp_cfg.get("trace_exec", False)),
        max_steps=int(interp_cfg.get("max_steps", 0) or 0),
        events=events,
    )

    try:
        # 1-2. globales + nivel de modulo: libs primero, main al final
        every = [*image.units.values(), image.main]
        for unit in every:
            unit.globals_frame = _build_globals(unit)
        for unit in every:
            _run_module_level(unit, evaluator)

        # 3. entrada. Dos modos, sin ambigüedad:
        #   - MODO SCRIPT: no hay 'main' y nadie pidió otra entrada -> las
        #     sentencias de nivel de módulo que acaban de correr (paso 2) SON
        #     el programa; termina 0. Es lo que hace 'ejecutable' a un .srcx
        #     estilo guion (sin 'fn main'), como test_.srcx.
        #   - ENTRADA EXPLÍCITA AUSENTE: si se pidió una entrada concreta
        #     ('--entry fn' o 'interpreter.entry' != 'main') y no existe, es un
        #     error real (RT009): el usuario nombró algo que no está.
        entry = image.main.functions.get(entry_name)
        if entry is None:
            if entry_name == "main":
                return 0  # script: el nivel de módulo fue el programa
            available = ", ".join(sorted(image.main.functions)) or "(ninguna)"
            raise MissingEntryError(
                f"la función de entrada '{entry_name}' no existe en el módulo "
                f"principal (funciones: {available}); ajusta "
                "'interpreter.entry' en .suriaX_config.yaml o usa --entry"
            )
        result = evaluator.call_function(image.main, entry, [])
    except Thrown as thrown:
        # un 'throw' que escapó de todo 'try/catch': error no capturado.
        print(f"error no capturado — throw {format_value(thrown.value)} "
              f"({thrown.ln}:{thrown.col})", file=sys.stderr)
        return 70
    except SuriaXRuntimeError as exc:
        print(f"error de runtime — {exc}", file=sys.stderr)
        return 70

    # 4. exit code
    return result if isinstance(result, int) and not isinstance(result, bool) else 0


def run_tests(image: Image, config: Optional[dict] = None) -> int:
    """Ejecuta los bloques ``test "..." { }`` del módulo PRINCIPAL.

    Cada test corre en su propio scope contra los globales de la unidad; un
    ``throw`` no capturado o un error de runtime lo marca como FALLIDO (no
    aborta la corrida: sigue con los demás). Devuelve 0 si todos pasan, 1 si
    alguno falla — el contrato del runner de pruebas (``test/main.py``)."""
    import sys

    interp_cfg = ((config or {}).get("interpreter") or {})
    evaluator = Evaluator(
        image,
        trace=bool(interp_cfg.get("trace_memory", False)),
        trace_exec=bool(interp_cfg.get("trace_exec", False)),
        max_steps=int(interp_cfg.get("max_steps", 0) or 0),
    )
    every = [*image.units.values(), image.main]
    for unit in every:
        unit.globals_frame = _build_globals(unit)
    for unit in every:
        _run_module_level(unit, evaluator)

    tests = image.main.tests
    if not tests:
        print("no hay bloques 'test' en el módulo principal")
        return 0

    passed = 0
    failed = 0
    for test in tests:
        try:
            evaluator._exec_block(test.body, Frame(parent=image.main.globals_frame))
            print(f"  PASS  {test.name}")
            passed += 1
        except (Thrown, SuriaXRuntimeError) as exc:
            detail = (f"throw {format_value(exc.value)}"
                      if isinstance(exc, Thrown) else str(exc))
            print(f"  FAIL  {test.name}  ({detail})", file=sys.stderr)
            failed += 1

    print(f"\ntests: {passed} pasaron, {failed} fallaron")
    return 1 if failed else 0


__all__ = ["run", "run_tests"]
