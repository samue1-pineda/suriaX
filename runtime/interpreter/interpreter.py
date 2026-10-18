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
from .errors import (ExcepcionDelPrograma, MissingEntryError,
                     SuriaXRuntimeError, UncaughtThrowError)
from .evaluator import Evaluator, ExpectFallido, Thrown
from .loader import Image, Unit
from .memory.pointer import Cell
from .values import (EnumNamespace, FunctionValue, Namespace, StructValue,
                     TypeValue, format_value)


_SK_STRUCT = 2    # espejo de SymbolKind.STRUCT


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
    """Statements sueltos a nivel de módulo, en orden de declaración.

    Corren con ``unit`` como unidad ACTIVA: los tipos de sus expresiones son
    índices en el pool de ESA unidad. Antes se quedaba puesta la principal, y
    el ``var`` de nivel superior de una librería resolvía sus tipos contra el
    pool del programa: un fallo interno si el índice no existía allí, y otro
    tipo —en silencio— si existía.
    """
    previa = evaluator.unit
    evaluator.unit = unit
    try:
        _ejecuta_nivel_de_modulo(unit, evaluator)
    finally:
        evaluator.unit = previa


def _ejecuta_nivel_de_modulo(unit: Unit, evaluator: Evaluator) -> None:
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
            tipo = unit.module.symbols.types.get(name)
            if tipo is not None and tipo.kind == _SK_STRUCT:
                # un STRUCT ('#from cosa #import Plano'): no tiene valor en
                # runtime que ligar; sus usos ya viajan con el nombre
                # canonico ('cosa.Plano') en el HIR. Un enum si lo tiene (sus
                # variantes), y se liga como cualquier miembro.
                continue
            target = evaluator._namespace_member(  # miembro real de la unidad
                Namespace(d.unit or d.lib), d.name, ln=decl.ln, col=decl.col,
            )
            unit.globals_frame.define(name, Cell(target, name=name))
        # function/struct/enum/extern/export: ya indexados o sin efecto aqui


def _destruir_globales(units: list, evaluator: Evaluator) -> None:
    """Los globales MUEREN al terminar el programa, como los locales de un
    bloque: del último declarado al primero, y las unidades al revés de como
    se inicializaron.

    ``units`` viene en orden de INICIALIZACIÓN (librerías primero, el
    programa al final), así que el programa destruye lo suyo primero y las
    librerías después: un global del programa puede depender de uno de una
    librería —se inicializó con él, lo usa su ``__free__`` (un ``File`` de
    registro)—, y al revés no. Es la regla de C++ para los estáticos.

    Antes no moría ninguno: el ``__free__`` de un global no corría nunca y un
    ``File`` global no llegaba a escribirse.

    Cuándo se llama: tras una terminación NORMAL (``main`` devolvió, o se
    acabó el guion) y tras CUALQUIER error que nadie atrapó —un ``throw``,
    una excepción ``EXCxxx`` o un ``RT``—. Todos desenrollan la pila y
    destruyen los locales de cada marco; las globales son la última pieza
    (un ``File`` global se vuelca). Decisión del mantenedor: un ``RT`` no es
    un ``std::abort``; el intérprete sigue vigilando el estado, así que un
    destructor que choca con él da su propio error, que se escribe DESPUÉS
    del original y no lo tapa. Si el fallo vino de destruir las globales, no
    se vuelve a intentar. ``sistema.proceso.salir`` no las destruye (es
    ``os._exit``).

    Qué destruir lo decide el VALOR (``Evaluator._tiene_destructor``) y no
    una lista del frontend como en un bloque: el HIR no lleva los drops de
    nivel de módulo (un campo nuevo en el esquema obligaría a regenerar el
    modelo de la VM). Da lo mismo que esa lista: un valor sin ningún
    ``__free__`` dentro no tiene nada que correr, y un puntero no es dueño.
    """
    for unit in reversed(units):
        if unit.globals_frame is None:
            continue
        previa = evaluator.unit
        evaluator.unit = unit
        try:
            for decl in reversed(unit.module.items):
                if decl.WhichOneof("node") != "statement" or \
                        decl.statement.WhichOneof("node") != "var_decl":
                    continue
                evaluator.destruir_global(unit.globals_frame,
                                          decl.statement.var_decl.name,
                                          ln=decl.statement.ln,
                                          col=decl.statement.col)
        except (SuriaXRuntimeError, Thrown) as fallo:
            # fuera de toda sentencia: la posicion es la del global, en el
            # archivo de SU unidad
            evaluator.set_error_unit(fallo)
            raise
        finally:
            evaluator.unit = previa


def _program_exception_classes() -> dict:
    """``"excepciones.<Tipo>"`` -> la clase de :mod:`errors` con su código
    (``IndiceFueraDeRango`` -> ``EXC002``)."""
    pending, classes = [ExcepcionDelPrograma], {}
    while pending:
        cls = pending.pop()
        if cls.tipo_excepcion:
            classes[f"excepciones.{cls.tipo_excepcion}"] = cls
        pending.extend(cls.__subclasses__())
    return classes


def _as_program_exception(fallo: Thrown, evaluator: Evaluator):
    """Un ``throw`` de una excepción del runtime (``excepciones.
    IndiceFueraDeRango``, la que lanza ``Vector``) como el error que es: con
    su código (``EXC002``), no como ``RT020: throw IndiceFueraDeRango{...}``.
    Es el MISMO tipo que lanza el acceso a un bloque, y sin atrapar tiene que
    decir lo mismo. ``None`` si lo lanzado es otra cosa."""
    name = fallo.tipo[1] if fallo.tipo is not None else None
    cls = _program_exception_classes().get(name or "")
    value = fallo.value
    if cls is None or not isinstance(value, StructValue):
        return None
    cell = value.fields.get("mensaje")
    message = cell.value if cell is not None else format_value(value)
    error = cls(message, ln=fallo.ln, col=fallo.col)
    if fallo.unit is not None and fallo.ln:
        error.set_file(fallo.unit, evaluator.unit_file(fallo.unit))
    return error


def _describe_uncaught(fallo, evaluator: Evaluator) -> str:
    """El mensaje de un error sin atrapar, con el archivo si no es del
    programa principal: ``error no capturado — RT020: throw 5 (ruta:3:9)``."""
    if isinstance(fallo, Thrown):
        own = _as_program_exception(fallo, evaluator)
        if own is not None:
            return f"excepción no capturada — {own}"
        error = UncaughtThrowError(f"throw {format_value(fallo.value)}",
                                   ln=fallo.ln, col=fallo.col)
        if fallo.unit is not None and fallo.ln:
            error.set_file(fallo.unit, evaluator.unit_file(fallo.unit))
        return f"error no capturado — {error}"
    if isinstance(fallo, ExcepcionDelPrograma):
        # una excepción del runtime (EXCxxx) que ningún 'catch' atrapó
        return f"excepción no capturada — {fallo}"
    return f"error de runtime — {fallo}"


def run(image: Image, config: Optional[dict] = None,
        events: Optional[list] = None, depurador=None) -> int:
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
    # 'sistema.argumento(i)': el 0 es el archivo que se ejecuta (como argv[0])
    from . import intrinsics
    intrinsics.fijar_argumentos(interp_cfg.get("argumentos") or [image.main.path])
    evaluator = Evaluator(
        image,
        trace=bool(interp_cfg.get("trace_memory", False)),
        trace_exec=bool(interp_cfg.get("trace_exec", False)),
        max_steps=int(interp_cfg.get("max_steps", 0) or 0),
        events=events,
        depurador=depurador,
    )

    every = [*image.units.values(), image.main]
    # ¿ya se estan destruyendo las globales? Si el error sale DE ahi, no se
    # vuelve a intentar: el destructor que fallo correria otra vez.
    destroying = False
    try:
        # 1-2. globales + nivel de modulo: libs primero, main al final
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
                # script: el nivel de módulo fue el programa, y al terminar
                # mueren sus globales como al volver de 'main'
                destroying = True
                _destruir_globales(every, evaluator)
                return 0
            available = ", ".join(sorted(image.main.functions)) or "(ninguna)"
            raise MissingEntryError(
                f"la función de entrada '{entry_name}' no existe en el módulo "
                f"principal (funciones: {available}); ajusta "
                "'interpreter.entry' en .suriaX_config.yaml o usa --entry"
            )
        result = evaluator.call_function(image.main, entry, [])
        # 'main' volvio: terminacion NORMAL. Los globales mueren aqui, despues
        # de los locales de 'main' y antes de entregar el codigo de salida (un
        # destructor que falla lo convierte en un 70).
        destroying = True
        _destruir_globales(every, evaluator)
    except (Thrown, SuriaXRuntimeError) as fallo:
        # un 'throw' que escapó de todo 'try/catch', una excepción EXCxxx que
        # nadie atrapó o un RT. El error se dice PRIMERO: lo que escriban
        # después los destructores no puede taparlo.
        print(_describe_uncaught(fallo, evaluator), file=sys.stderr)
        if not destroying:
            # los locales ya murieron al desenrollar; mueren también las
            # globales, sea cual sea el error (ver '_destruir_globales')
            try:
                _destruir_globales(every, evaluator)
            except (Thrown, SuriaXRuntimeError) as otro:
                print(f"además, al destruir los globales: "
                      f"{_describe_uncaught(otro, evaluator)}", file=sys.stderr)
        return 70

    # 4. exit code
    return result if isinstance(result, int) and not isinstance(result, bool) else 0


def run_tests(image: Image, config: Optional[dict] = None,
              depurador=None) -> int:
    """Ejecuta los bloques ``test "..." { }`` del módulo PRINCIPAL.

    Cada prueba corre AISLADA: con sus globales RECIÉN iniciadas (las de
    todas las unidades: se vuelve a correr el nivel de módulo) y destruidas
    al terminarla. Así el resultado de una prueba no depende de cuáles
    corrieron antes (decisión del mantenedor); antes se compartían, y una
    prueba que cambiaba una global hacía fallar a la siguiente.

    Un ``throw`` no capturado, un ``expect`` que no se cumple o un error de
    ejecución la marca como FALLIDA (no aborta la corrida: sigue con las
    demás); también un fallo al iniciar o al destruir sus globales. Aciertos
    y fallos salen por el MISMO canal (la salida estándar), en el orden en que
    corren: antes los fallos iban a la de error y en una tubería se
    desordenaban. Devuelve 0 si todas pasan, 1 si alguna falla — el contrato
    del runner de pruebas (``test/main.py``)."""
    import sys

    from .memory import native
    if native.AVAILABLE:
        native.reset()      # como 'run': las celdas de ESTA corrida

    interp_cfg = ((config or {}).get("interpreter") or {})
    evaluator = Evaluator(
        image,
        trace=bool(interp_cfg.get("trace_memory", False)),
        trace_exec=bool(interp_cfg.get("trace_exec", False)),
        max_steps=int(interp_cfg.get("max_steps", 0) or 0),
        depurador=depurador,
    )
    every = [*image.units.values(), image.main]

    tests = image.main.tests
    passed = 0
    failed = 0
    if not tests:
        print("no hay bloques 'test' en el módulo principal")
    for test in tests:
        detalle = _run_isolated_test(evaluator, every, test)
        if detalle is None:
            print(f"  PASS  {test.name}")
            passed += 1
        else:
            print(f"  FAIL  {test.name}  ({detalle})")
            failed += 1
        # lo que la prueba escribió por la salida de error (un 'stdp.eprint')
        # no puede adelantarse a su resultado en una consola
        sys.stdout.flush()

    if tests:
        print(f"\ntests: {passed} pasaron, {failed} fallaron")
    return 1 if failed else 0


def _run_isolated_test(evaluator: Evaluator, units: list, test) -> Optional[str]:
    """Corre UNA prueba con globales propias: ``None`` si pasó, o por qué
    falló.

    1. globales nuevas en cada unidad y su nivel de módulo, como al empezar
       un programa (librerías primero);
    2. la prueba y sus cláusulas (``_correr_prueba``);
    3. sus globales mueren al terminar, en orden inverso, con la regla de
       ``run``: pase o falle, y falle como falle (``expect``, ``throw``,
       ``EXCxxx`` o un ``RT``).
    """
    for unit in units:
        unit.globals_frame = _build_globals(unit)
    detalle = None
    try:
        for unit in units:
            _run_module_level(unit, evaluator)
    except (Thrown, SuriaXRuntimeError) as fallo:
        detalle = f"al iniciar los globales: {_describe_failure(fallo, evaluator)}"
    else:
        # el programa principal es la ultima unidad (se inicia al final)
        detalle = _correr_prueba(evaluator, test, units[-1].globals_frame)
    try:
        _destruir_globales(units, evaluator)
    except (Thrown, SuriaXRuntimeError) as fallo:
        previo = f"{detalle}; además falló" if detalle else "falló"
        detalle = (f"{previo} al destruir sus globales: "
                   f"{_describe_failure(fallo, evaluator)}")
    return detalle


def _correr_prueba(evaluator: Evaluator, test, globales: Frame) -> Optional[str]:
    """Corre UNA prueba: ``None`` si pasó, o por qué falló.

    Falla con un ``expect`` que no se cumple, un ``throw`` que nadie atrapa o
    un error de ejecucion. ``errfinally`` corre solo si fallo; ``finally``,
    siempre y despues. Cada clausula corre en su propio ambito sobre los
    globales (no ve los locales del cuerpo, que ya murieron). Si una clausula
    falla a su vez, la prueba falla y se dice cual fue."""
    fallo = _fallo_de(evaluator, test.body, globales)
    detalle = _describe_failure(fallo, evaluator) if fallo is not None else None
    if fallo is not None and test.HasField("errfinally"):
        en_clausula = _fallo_de(evaluator, test.errfinally, globales)
        if en_clausula is not None:
            detalle += ("; ademas fallo su 'errfinally': "
                        f"{_describe_failure(en_clausula, evaluator)}")
    if test.HasField("finally_block"):
        en_clausula = _fallo_de(evaluator, test.finally_block, globales)
        if en_clausula is not None:
            previo = f"{detalle}; ademas fallo" if detalle else "fallo"
            detalle = (f"{previo} su 'finally': "
                       f"{_describe_failure(en_clausula, evaluator)}")
    return detalle


def _fallo_de(evaluator: Evaluator, bloque, globales: Frame):
    """Ejecuta ``bloque``; ``None`` si termino bien, o el fallo que lo cortó
    (``ExpectFallido``, ``Thrown`` o un error de ejecución)."""
    try:
        evaluator._exec_block(bloque, Frame(parent=globales))
    except (ExpectFallido, Thrown, SuriaXRuntimeError) as exc:
        return exc
    return None


def _describe_failure(fallo, evaluator: Evaluator) -> str:
    """El porqué de una prueba fallida, en una línea."""
    if isinstance(fallo, ExpectFallido):
        return fallo.mensaje()
    if isinstance(fallo, Thrown):
        archivo = evaluator.unit_file(fallo.unit)
        donde = f"{archivo}:" if archivo else ""
        return (f"throw {format_value(fallo.value)} sin atrapar  "
                f"[{donde}{fallo.ln}:{fallo.col}]")
    return str(fallo)


__all__ = ["run", "run_tests"]
