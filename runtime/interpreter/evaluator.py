"""El tree-walk: ``exec_stmt`` / ``eval_expr`` por despacho O(1) (secc. 4).

Recorre los messages del HIR despachando por ``WhichOneof`` contra tablas
``str -> método`` construidas UNA vez por instancia (mismo patrón de
tabla-de-despacho que todo el frontend). No re-decide semántica: ejecuta lo
que el HIR trae resuelto — tipos en ``restype``, hooks en ``HookRef``,
mutabilidad en ``AddrOf.mut``.

Las INSTRUCCIONES DE MEMORIA (``&``, deref implícito, ``move``, ``free``)
delegan en :mod:`memory.pointer`: la celda es quien valida su estado
(use-after-move/free) — el evaluator solo enruta.

Control de flujo por señales (excepciones internas ``_Return``/``_Break``/
``_Continue``): coste solo cuando ocurren, cero banderas en el camino
caliente.
"""

from __future__ import annotations

import math
import os
import re
from typing import Any, List, Optional

from .enviroment.environment import Frame
from .errors import (
    ConversionError, DestructorThrewError, DivisionByZeroError, ExcepcionDelPrograma,
    ShiftOutOfRangeError,
    FinallyThrewError,
    MissingReturnError,
    IndexOutOfRangeError, InvalidCastRuntimeError, InvalidFreeError,
    MissingIntrinsicError, NotCallableError, NotIndexableError,
    NullDereferenceError, StackOverflowError, StepLimitError,
    SuriaXRuntimeError, UnsupportedNodeError,
)
from .hook.dispatch import hook_key, ref_key, type_key
from . import intrinsics
from .memory.block import Block
from .memory.pointer import Cell, CellState, Pointer
from .values import (
    EnumItem, EnumNamespace, EnumValue, FunctionValue, LambdaValue, Namespace,
    StructValue,
    TypeValue, VariantCtor,
    copy_on_bind, format_value,
)


#: los primitivos que 'print(x)' escribe sin hook (el dueño de su HookRef)
_PRINTABLE_PRIMITIVES = frozenset({"int", "float", "bool", "char", "str", "byte"})


class _Return(Exception):
    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value


def _void_kind_value() -> int:
    """El valor de ``TypeKind.VOID``, leído del esquema (no cableado)."""
    from V0.src.HIR.stubs import load_hir_pb2
    return load_hir_pb2().TypeKind.Value("VOID")


#: se resuelven una vez por proceso: el enum del esquema no cambia en caliente.
_VOID_KIND = None
_POINTER_KIND = None
_NOMINAL_KIND = None
_ERROR_KIND = None
#: (ERROR, NULLABLE, NOMINAL), para escribir un valor con su tipo
_KINDS_TEXTO = None

_M64 = (1 << 64) - 1

#: el prefijo de la ruta PUBLICA de una libreria de la stdlib
#: (``Module.source_file``), el mismo que escribe el linker
_STDLIB_PREFIX = "<stdlib>/"

#: escapes que se escriben en la representacion de una cadena o un char: los
#: mismos que acepta el lexer
_ESCAPES = {"\\": "\\\\", "\n": "\\n", "\t": "\\t", "\r": "\\r", "\0": "\\0"}


def _cadena_repr(s: str, comilla: str) -> str:
    """``"hola\\n"`` / ``'a'``: el texto como se escribiria en el fuente."""
    cuerpo = "".join(_ESCAPES.get(c, "\\" + c if c == comilla else c) for c in s)
    return comilla + cuerpo + comilla


_FORMATO = re.compile(r"(0?)([1-9][0-9]*)?(?:\.([0-9]+))?([dxXbof]?)")


def _con_formato(valor: Any, tipo, texto: str, spec: str) -> str:
    """El ``texto`` de ``valor`` con el formato ``[0][ancho][.precision][tipo]``.

    Es un algoritmo PROPIO y no el ``format`` de Python, para que la VM haga
    exactamente lo mismo: ``d x X b o`` escriben el valor absoluto en esa base
    con el signo delante (``-ff``); ``f``, con la precision pedida (6 si no);
    el ancho rellena a la IZQUIERDA un numero (con ``0`` despues del signo si
    se pidio) y a la DERECHA todo lo demas.
    """
    m = _FORMATO.fullmatch(spec)
    if m is None:
        return texto
    cero, ancho, precision, clase = m.groups()
    if valor is not None and clase:
        if clase == "d":
            texto = str(valor)
        elif clase in "xXbo":
            base = {"x": "x", "X": "X", "b": "b", "o": "o"}[clase]
            texto = ("-" if valor < 0 else "") + format(abs(valor), base)
        elif clase == "f":
            texto = _fijo(float(valor), int(precision) if precision else 6)
    if not ancho or len(texto) >= int(ancho):
        return texto
    ancho = int(ancho)
    numero = tipo is not None and tipo.kind in (_TK_INT, _TK_FLOAT, _TK_BYTE) \
        and valor is not None
    if numero and cero:
        signo = "-" if texto.startswith("-") else ""
        return signo + texto[len(signo):].rjust(ancho - len(signo), "0")
    return texto.rjust(ancho) if numero else texto.ljust(ancho)


def _fijo(x: float, precision: int) -> str:
    """``{x:.2f}``: redondeo correcto, 'inf', '-inf' y 'nan' como Python."""
    if math.isnan(x):
        return "nan"
    if math.isinf(x):
        return "inf" if x > 0 else "-inf"
    return f"{x:.{precision}f}"


def _con_signo(x: int) -> int:
    x &= _M64
    return x - (1 << 64) if x >> 63 else x


def _splitmix64(x: int) -> int:
    """El finalizador de splitmix64: mezcla los 64 bits de un entero."""
    z = (x + 0x9E3779B97F4A7C15) & _M64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _M64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _M64
    return _con_signo(z ^ (z >> 31))


def _fnv1a(datos: bytes) -> int:
    """FNV-1a de 64 bits."""
    h = 0xCBF29CE484222325
    for b in datos:
        h = ((h ^ b) * 0x100000001B3) & _M64
    return _con_signo(h)


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class ExpectFallido(Exception):
    """Un ``expect`` que no se cumplio: la prueba en curso TERMINA.

    No es un :class:`Thrown`: ningun ``catch`` lo atrapa (una prueba no puede
    rescatarse de su propia comprobacion). Los ``finally`` que atraviesa si
    corren, como con un ``return``. Lo recibe ``interpreter.run_tests``.

    ``texto`` es la condicion como se escribio; ``valores``, los dos lados de
    una comparacion (``None`` si la condicion no es una)."""

    __slots__ = ("texto", "ln", "col", "valores")

    def __init__(self, texto: str, ln: int = 0, col: int = 0, valores=None) -> None:
        self.texto = texto
        self.ln = ln
        self.col = col
        self.valores = valores

    def mensaje(self) -> str:
        detalle = ""
        if self.valores is not None:
            izquierda, derecha = self.valores
            detalle = (f"  (izquierda: {format_value(izquierda)}, "
                       f"derecha: {format_value(derecha)})")
        return f"expect falló: {self.texto}{detalle}  [{self.ln}:{self.col}]"


class Thrown(Exception):
    """Propagación de un ``throw`` por la pila (modelo de excepciones).

    Distinta de :class:`SuriaXRuntimeError`: esto es control de flujo del
    PROGRAMA (lo captura un ``try``/``catch``), no un fallo del intérprete.
    Si escapa hasta la raíz, ``interpreter.run`` la reporta como error de
    runtime no capturado."""

    __slots__ = ("value", "ln", "col", "tipo", "unit")

    def __init__(self, value: Any, ln: int = 0, col: int = 0,
                 tipo=None, unit=None) -> None:
        self.value = value
        self.ln = ln
        self.col = col
        #: clave del tipo ESTATICO del valor lanzado (el que decidio la
        #: Semantica), o None si el HIR no lo trae. Es lo que filtra el
        #: 'catch' — ver '_atrapa'.
        self.tipo = tipo
        #: unidad (``loader.Unit``) del 'throw': ``ln``/``col`` son de SU
        #: archivo, que puede ser una libreria. La pone ``exec_stmt``.
        self.unit = unit


# TypeKind del esquema (valores estables del .proto; ver hir.proto)
_TK_BOOL, _TK_INT, _TK_FLOAT, _TK_CHAR, _TK_STR = 2, 3, 4, 5, 6
_TK_BYTE = 12   # 'byte': un int de Python en 0..255
_TK_NOMINAL = 9   # espejo de TypeKind.NOMINAL en el esquema del HIR
_TK_POINTER, _TK_NULLABLE, _TK_META = 7, 8, 10
_TK_FUNCTION = 13  # 'fn(A) -> R': args = parametros, inner = retorno
_TK_ERROR = 11     # 'error T': transparente en la ruta de exito
_SK_ENUM = 3      # espejo de SymbolKind.ENUM


class Evaluator:
    __slots__ = ("image", "trace", "trace_exec", "max_steps", "steps",
                 "events", "depth", "unit", "_stmt_dispatch", "_expr_dispatch",
                 "_index_kind", "_index_set_kind", "_eq_kind", "_free_kind", "_structs", "_len_kind",
                 "_hash_kind", "_print_kind", "_cmp_kind",
                 "_temporales", "_enums", "_expect_expr", "_expect_valores",
                 "depurador", "_user_call", "_stdlib_units")

    def __init__(self, image, *, trace: bool = False, max_steps: int = 0,
                 trace_exec: bool = False,
                 events: Optional[List[str]] = None,
                 depurador=None) -> None:
        self.image = image
        # quien decide cuando parar (ver 'depurador.py'). None = nadie mira:
        # el unico coste es la comparacion de 'exec_stmt'.
        self.depurador = depurador
        self.trace = trace          # traza de MEMORIA (&, move, free, catch)
        self.trace_exec = trace_exec  # traza de EJECUCION (llamadas/sentencias)
        self.max_steps = max_steps
        self.steps = 0
        # sumidero de eventos: si el llamador pasa una lista, la traza se
        # ACUMULA ahi (para volcarla a dumps/<f>.debug.txt) en vez de -- o
        # ademas de -- imprimirse. None = solo consola.
        self.events: Optional[List[str]] = events
        self.depth = 0
        # la condicion del 'expect' en curso y, si es una comparacion, sus
        # dos lados ya evaluados (para citarlos si falla sin evaluar dos veces)
        self._expect_expr = None
        self._expect_valores = None
        # temporales de la sentencia en curso: (valor, HookRef). Ver
        # 'exec_stmt' y '_registrar_temporal'.
        self._temporales: List[Any] = []
        # (unidad, ln, col) de la llamada MAS INTERNA del codigo del usuario
        # a la stdlib, o None fuera de la stdlib. Es la posicion que lleva una
        # excepcion que la stdlib lanza (H03): ver 'call_function',
        # 'set_error_unit' y '_thrown_at_user_call'.
        self._user_call = None
        # id(unidad) -> ¿es de la stdlib? (se pregunta en cada llamada)
        self._stdlib_units: dict = {}
        # unidad cuyo codigo se esta ejecutando. Hace falta porque los tipos
        # de las expresiones viajan como INDICE en el pool de SU unidad
        # (Expr.type_id, esquema v2): resolverlos exige saber de que modulo
        # salio la expresion. La monta 'call_function' y la restaura al salir.
        self.unit = image.main
        # (unidad, nombre) -> (Unit, EnumDecl), para escribir un enum por su
        # NOMBRE en un f-string. Se arma la primera vez que hace falta.
        self._enums: Optional[dict] = None
        self._structs: Optional[dict] = None
        # valores enteros de los kinds de hook despachados por sintaxis ('v[i]',
        # 'v[i]=x', 'a==b') contra image.hooks — sin cablear el número del enum.
        from V0.src.HIR.stubs import load_hir_pb2
        _hk = load_hir_pb2().HookKind
        self._index_kind = _hk.Value("INDEX")
        self._index_set_kind = _hk.Value("INDEX_SET")
        self._len_kind = _hk.Value("LEN")
        self._hash_kind = _hk.Value("HASH")
        self._print_kind = _hk.Value("PRINT")
        self._eq_kind = _hk.Value("EQ")
        self._cmp_kind = _hk.Value("CMP")
        self._free_kind = _hk.Value("FREE")

        self._stmt_dispatch = {
            "block": self._stmt_block,
            "var_decl": self._stmt_var_decl,
            "type_decl": self._stmt_type_decl,
            "if_stmt": self._stmt_if,
            "while_stmt": self._stmt_while,
            "match_stmt": self._stmt_match,
            "return_stmt": self._stmt_return,
            "break_stmt": self._stmt_break,
            "continue_stmt": self._stmt_continue,
            "move_stmt": self._stmt_move,
            "free_stmt": self._stmt_free,
            "expr_stmt": self._stmt_expr,
            "import_binding": self._stmt_import_binding,
            "throw_stmt": self._stmt_throw,
            "expect_stmt": self._stmt_expect,
            "try_stmt": self._stmt_try,
        }
        self._expr_dispatch = {
            "literal": self._expr_literal,
            "interp": self._expr_interp,
            "identifier": self._expr_identifier,
            "unary": self._expr_unary,
            "addr_of": self._expr_addr_of,
            "binary": self._expr_binary,
            "assignment": self._expr_assignment,
            "call": self._expr_call,
            "index": self._expr_index,
            "member": self._expr_member,
            "sizeof": self._expr_sizeof,
            "cast_expr": self._expr_cast,
            "move_expr": self._expr_move,
            "struct_literal": self._expr_struct_literal,
            "lambda_expr": self._expr_lambda,
        }

    # ------------------------------------------------------------------ #
    # traza (un solo punto de emisión: consola y/o sumidero de eventos)
    # ------------------------------------------------------------------ #
    def emit(self, text: str) -> None:
        line = f"{'  ' * self.depth}{text}"
        if self.events is not None:
            self.events.append(line)
        else:
            print(line)

    # ------------------------------------------------------------------ #
    # funciones
    # ------------------------------------------------------------------ #
    def call_function(self, unit, decl, args: List[Any], *,
                      ln: int = 0, col: int = 0) -> Any:
        """Ejecuta una ``fn`` del HIR (o su intrínseco si es prototipo)."""
        if not decl.HasField("body"):
            native = intrinsics.lookup(decl.name)
            if native is None:
                raise MissingIntrinsicError(
                    f"el prototipo '{decl.name}' no tiene intrínseco "
                    "registrado en el host (runtime/interpreter/intrinsics.py)",
                    ln=ln, col=col,
                )
            if self.trace_exec:
                self.emit(f"[call] {decl.name}(intrinseco) "
                          f"args={[format_value(a) for a in args]}")
            if decl.name == "__release__" and args and isinstance(args[0], Block):
                # un bloque POSEE sus celdas no vacias: soltarlo las destruye
                # (las que se sacaron con 'mem.take' o 'mem.move' ya no estan).
                # Las celdas las marca liberadas el intrinseco.
                for celda in reversed(args[0].cells):
                    if celda.state is CellState.LIVE and celda.value is not None:
                        self._destruir_por_tipo(celda.value, ln=ln, col=col)
            try:
                return native(*args)
            except SuriaXRuntimeError as exc:
                # el host no sabe desde dónde lo llamaron: la posición es la
                # del sitio de llamada, igual que en la VM
                raise exc.ubicar(ln, col)

        if self.trace_exec:
            self.emit(f"[call] {decl.name}("
                      f"{', '.join(format_value(a) for a in args)})  {ln}:{col}")
        self.depth += 1

        frame = Frame(parent=unit.globals_frame)
        # ¿esta llamada CRUZA del codigo del usuario a la stdlib? Entonces su
        # posicion es la que llevara una excepcion lanzada ahi dentro (H03).
        previous_user_call = self._user_call
        if self._is_stdlib(unit) and not self._is_stdlib(self.unit):
            self._user_call = (self.unit, ln, col)
        for param, value in zip(decl.params, args):
            # Semántica de VALOR: el llamado recibe SU copia, así que mutar
            # un parámetro no toca lo del llamador. Un parámetro declarado
            # 'ptr' NO se copia: un puntero es un préstamo, y copiarlo
            # rompería justo lo que existe para permitir — que un hook o un
            # método muten el receptor. Lo decide el TIPO DECLARADO, que es
            # quien lo dice en el lenguaje.
            frame.define(param.name,
                         Cell(value if self._es_prestamo(unit, param)
                              else self._as_declared(unit, param.type_id,
                                                     copy_on_bind(value)),
                              name=param.name))
        result = None
        devolvio = False
        previa = self.unit
        self.unit = unit
        if self.depurador is not None:
            self.depurador.entra(unit, decl, frame)
        try:
            # El cuerpo corre en el MISMO marco que los parámetros: la
            # Semántica los declara en el mismo scope FUNCTION (un local no
            # puede llamarse como un parámetro), y los drops del cuerpo
            # incluyen los parámetros que la función posee. Con un marco hijo,
            # '_drop_scope' no los encontraba y no se destruían nunca.
            self._exec_block(decl.body, frame)
        except _Return as ret:
            result = ret.value
            devolvio = True
        except RecursionError:
            # La pila de Python se agotó: el PROGRAMA anidó demasiadas
            # llamadas. Se convierte aquí, en el marco donde ocurrió, para
            # reportar la llamada y la profundidad. Si construir el error
            # vuelve a agotar la pila, el marco de arriba (con más margen)
            # atrapa ese RecursionError y lo convierte él: siempre sale un
            # RT019, nunca un traceback.
            raise StackOverflowError(
                f"desbordamiento de pila al llamar a '{decl.name}': "
                f"{self.depth} llamadas anidadas (¿una recursión sin caso "
                "base?)",
                ln=ln, col=col,
            ) from None
        finally:
            if self.depurador is not None:
                self.depurador.sale()
            self.unit = previa
            self._user_call = previous_user_call
            self.depth -= 1
        # Caerse por el final de una función con tipo de retorno entregaba
        # 'null' en silencio. El tipo de retorno viaja en el HIR, así que aquí
        # se sabe que faltaba un valor.
        if not devolvio and self._devuelve_valor(unit, decl):
            raise MissingReturnError(
                f"la función '{decl.name}' terminó sin devolver un valor y su "
                "tipo de retorno no es 'void'",
                ln=ln, col=col,
            )
        if self.trace_exec:
            self.emit(f"[ret ] {decl.name} -> {format_value(result)}")
        return result

    def call_lambda(self, lam: LambdaValue, args: List[Any], *,
                    ln: int = 0, col: int = 0) -> Any:
        """Ejecuta una ``lambda`` con ``args``, como una ``fn``: sus
        parametros en un marco propio (con la misma semantica de valor), su
        cuerpo, sus drops y su ``return``. Lo distinto es el PADRE del marco:
        el de donde se escribio, asi que lo que lee del entorno (sus
        capturas) lo encuentra vivo y sin copiar."""
        node = lam.node
        unit = lam.unit
        if self.trace_exec:
            self.emit(f"[call] {lam.name}("
                      f"{', '.join(format_value(a) for a in args)})  {ln}:{col}")
        self.depth += 1
        frame = Frame(parent=lam.frame)
        for param, value in zip(node.params, args):
            frame.define(param.name,
                         Cell(value if self._es_prestamo(unit, param)
                              else self._as_declared(unit, param.type_id,
                                                     copy_on_bind(value)),
                              name=param.name))
        result = None
        returned = False
        previous = self.unit
        self.unit = unit
        if self.depurador is not None:
            self.depurador.entra(unit, lam, frame)
        try:
            self._exec_block(node.body, frame)
        except _Return as ret:
            result = ret.value
            returned = True
        except RecursionError:
            raise StackOverflowError(
                f"desbordamiento de pila al llamar a la lambda de la linea "
                f"{lam.ln}: {self.depth} llamadas anidadas",
                ln=ln, col=col,
            ) from None
        finally:
            if self.depurador is not None:
                self.depurador.sale()
            self.unit = previous
            self.depth -= 1
        if not returned and self._devuelve_valor(unit, node):
            raise MissingReturnError(
                f"la lambda de la linea {lam.ln} termino sin devolver un valor "
                "y su tipo de retorno no es 'void'",
                ln=ln, col=col,
            )
        if self.trace_exec:
            self.emit(f"[ret ] {lam.name} -> {format_value(result)}")
        return result

    @staticmethod
    def _as_declared(unit, type_id: int, value: Any) -> Any:
        """``value`` ligado a algo declarado de tipo ``type_id``: un
        :class:`EnumItem` que entra en un ``int`` (``var int n =
        Color.VERDE;``) deja de ser el item y es el entero. Si no, un
        generico que recibiera ``n`` lo escribiria como ``VERDE`` (A08)."""
        if type(value) is EnumItem and type_id:
            types = unit.module.types
            if type_id < len(types) and types[type_id].kind == _TK_INT:
                return int(value)
        return value

    @staticmethod
    def _es_prestamo(unit, param) -> bool:
        """¿El parámetro está declarado como puntero (un préstamo)?

        El pool de tipos es de la UNIDAD, igual que en el retorno: se resuelve
        contra la unidad donde vive la función, no contra la del llamador.
        """
        global _POINTER_KIND
        if _POINTER_KIND is None:
            from V0.src.HIR.stubs import load_hir_pb2
            _POINTER_KIND = load_hir_pb2().TypeKind.Value("POINTER")
        type_id = param.type_id
        types = unit.module.types
        if type_id == 0 or type_id >= len(types):
            return False
        return types[type_id].kind == _POINTER_KIND

    @staticmethod
    def _devuelve_valor(unit, decl) -> bool:
        """¿``decl`` declara un tipo de retorno distinto de ``void``?

        El pool de tipos es de la UNIDAD, así que el ``type_id`` se resuelve
        contra el de la unidad donde vive la función — no contra el del
        llamador. Resolverlo en la unidad equivocada daba a ``printf`` de
        ``IO.stdpf`` un tipo de retorno que no era el suyo.

        El índice 0 del pool es "sin tipo" y ``void`` es un tipo con nombre:
        los dos significan "no hay valor que devolver", pero por motivos
        distintos, así que se preguntan los dos.
        """
        global _VOID_KIND
        if _VOID_KIND is None:
            _VOID_KIND = _void_kind_value()
        type_id = decl.return_type_id
        if type_id == 0:
            return False
        types = unit.module.types
        if type_id >= len(types):
            return False
        return types[type_id].kind != _VOID_KIND

    # ------------------------------------------------------------------ #
    # statements
    # ------------------------------------------------------------------ #
    def _exec_block(self, block, frame: Frame) -> None:
        if not block.drops:
            # camino rapido: la inmensa mayoria de los bloques no destruye
            # nada, y no deben pagar el 'try' ni la llamada extra.
            for stmt in block.statements:
                self.exec_stmt(stmt, frame)
            return
        try:
            for stmt in block.statements:
                self.exec_stmt(stmt, frame)
        finally:
            # 'finally' y no un simple final: el bloque tambien se cierra por
            # 'return', 'break', 'continue' y 'throw', y en todos esos casos
            # los valores mueren igual. Un drop que solo corriera en la salida
            # normal seria una fuga en cuanto hubiera un 'return' temprano.
            self._drop_scope(block, frame)

    def _drop_scope(self, block, frame: Frame) -> None:
        """Destruye los valores del bloque que sigan VIVOS.

        La lista de candidatos es estatica (la decidio la Semantica por el
        TIPO); lo que es dinamico es cuales siguen vivos. Esa pregunta no
        necesita maquinaria nueva: la celda ya lleva su estado, porque es la
        misma que hace cumplir el use-after-move y el use-after-free. Asi un
        'move' dentro de un 'if' sale correcto sin analisis de flujo — si la
        rama corrio, la celda esta MOVED y aqui no se toca.
        """
        for drop in block.drops:
            cell = self._celda_de_ruta(frame, drop.path)
            if cell is None:
                continue
            if drop.by_type:
                self._destruir_por_tipo(cell.value)
                cell.free()
                if self.trace:
                    self.emit(f"[mem] drop -> celda '{'.'.join(drop.path)}' "
                              "(por su tipo)")
                continue
            bound = self.image.hooks.get(ref_key(drop.hook))
            # un dueño 'R?' que vale null no tiene nada que destruir: 'T?' es
            # un envoltorio y hereda la respuesta de lo que envuelve (A09).
            # Antes se llamaba al '__free__' CON null: RT004 si leía un campo,
            # o una destrucción contada de más.
            if bound is not None and cell.value is not None:
                self._destruir(bound, Pointer(cell, mut=True),
                               drop.hook.owner_type)
            cell.free()
            if self.trace:
                self.emit(f"[mem] drop -> celda '{'.'.join(drop.path)}'")

    def _celda_de_ruta(self, frame: Frame, path) -> Optional[Cell]:
        """La celda al final de ``path``, o ``None`` si algo por el camino ya
        no esta vivo.

        Comprueba el estado a CADA paso y nunca llama a ``read()``: esto corre
        dentro de un ``finally``, asi que una excepcion aqui taparia la que
        venia en curso (un 'throw' del programa, por ejemplo). Los estados no
        son un error — son la respuesta: si el valor ya se movio o se libero,
        no hay nada que destruir.
        """
        cell = frame.cells.get(path[0])
        for campo in path[1:]:
            if cell is None or cell.state is not CellState.LIVE:
                return None
            valor = cell.value
            if not isinstance(valor, StructValue):
                return None
            cell = valor.fields.get(campo)
        if cell is None or cell.state is not CellState.LIVE:
            return None
        return cell

    def exec_stmt(self, stmt, frame: Frame) -> None:
        try:
            self._tick(stmt.ln, stmt.col)
        except SuriaXRuntimeError as fallo:
            self.set_error_unit(fallo)
            raise
        if self.depurador is not None:
            self.depurador.en_sentencia(self.unit, stmt, frame)
        which = stmt.WhichOneof("node")
        handler = self._stmt_dispatch.get(which)
        if handler is None:
            raise UnsupportedNodeError(
                f"sentencia '{which}' sin soporte de ejecución",
                ln=stmt.ln, col=stmt.col,
            )
        # TEMPORALES. Un valor que posee recursos y que nadie recibe muere al
        # terminar la SENTENCIA que lo produjo — 'recibe(R{...})' no le da
        # dueno a nadie. La marca es el largo de la pila: lo que se apile
        # durante esta sentencia se suelta al salir de ella, tambien si sale
        # por una excepcion (un 'throw' del programa no debe filtrar).
        marca = len(self._temporales)
        try:
            handler(stmt, frame)
        except (SuriaXRuntimeError, Thrown, ExpectFallido) as fallo:
            # la sentencia MAS INTERNA que ve el error es la que fallo: su
            # unidad es la del archivo de la posicion (antes un error en una
            # libreria salia con su linea y sin decir de que archivo era).
            self.set_error_unit(fallo)
            # con un depurador: se detiene AQUI, en la sentencia que fallo y
            # con la pila entera. Sin el, esta rama solo relanza.
            if self.depurador is not None:
                self._avisa_del_error(fallo, stmt, frame)
            raise
        finally:
            if len(self._temporales) > marca:
                self._soltar_temporales(marca)

    def set_error_unit(self, fallo, unit=None) -> None:
        """Situa ``fallo`` en ``unit`` (por defecto, la unidad activa): su
        ``ln``/``col`` son de ESE archivo.

        Solo la primera vez, y a un error de ejecucion solo si ya tiene
        posicion: uno que nace sin ella (un intrinseco) la recibe despues con
        ``ubicar`` en la sentencia que lo llamo, que es la que lo situa. Un
        ``expect`` no se situa: solo existe en el programa principal."""
        unit = unit if unit is not None else self.unit
        if unit is None:
            return
        if isinstance(fallo, Thrown):
            if fallo.unit is None:
                fallo.unit = unit
        elif isinstance(fallo, SuriaXRuntimeError):
            if fallo.unit is None and isinstance(fallo, ExcepcionDelPrograma) \
                    and self._user_call is not None and self._is_stdlib(unit):
                # una excepcion que nace DENTRO de la stdlib (un intrinseco de
                # 'sistema.archivos', 'text.parse_int', un indice de 'mem')
                # lleva la posicion de la llamada del programa, como promete
                # 'excepciones' (H03). Un error RT (no atrapable) conserva la
                # de la libreria: ese es un fallo de ella, no del llamador.
                caller, ln, col = self._user_call
                fallo.ln, fallo.col = ln, col
                fallo.set_file(caller, self.unit_file(caller))
            elif fallo.ln and fallo.unit is None:
                fallo.set_file(unit, self.unit_file(unit))

    def _is_stdlib(self, unit) -> bool:
        """¿``unit`` es de la stdlib (``<stdlib>/...``)? El programa y las
        librerias del proyecto no: su posicion si le dice algo al usuario."""
        if unit is None:
            return False
        key = id(unit)
        known = self._stdlib_units.get(key)
        if known is None:
            known = unit is not self.image.main and \
                (unit.module.source_file or "").startswith(_STDLIB_PREFIX)
            self._stdlib_units[key] = known
        return known

    def unit_file(self, unit) -> Optional[str]:
        """El archivo de ``unit`` para un mensaje de error: ``None`` si es el
        programa principal (su posicion sale sin archivo, como al compilar).

        De una libreria, su ruta PUBLICA (``Module.source_file``):
        ``<stdlib>/array/vector.libsrx`` o relativa a la raiz del proyecto
        (``lib/util.libsrx``). Es la que viaja en el ``.phir``: corta, dice si
        es de la stdlib o del proyecto, y es la misma en cualquier maquina
        que ejecute ese ``.phir``."""
        if unit is None or unit is self.image.main:
            return None
        return unit.module.source_file or os.path.basename(unit.path)

    def _avisa_del_error(self, fallo, stmt, frame: Frame) -> None:
        if isinstance(fallo, Thrown):
            atrapable, codigo = True, "throw"
            descripcion = f"throw {format_value(fallo.value)}"
        elif isinstance(fallo, ExpectFallido):
            atrapable, codigo = False, "expect"
            descripcion = f"expect falló: {fallo.texto}"
        else:
            atrapable = isinstance(fallo, ExcepcionDelPrograma)
            codigo = getattr(fallo, "code", "") or type(fallo).__name__
            descripcion = str(fallo)
        self.depurador.en_error(fallo, atrapable, codigo, descripcion,
                                self.unit, stmt, frame)

    def _soltar_temporales(self, marca: int) -> None:
        while len(self._temporales) > marca:
            valor, hook = self._temporales.pop()
            if hook is None:
                # POR SU TIPO: posee sin declarar '__free__', o es un 'T'
                self._destruir_por_tipo(valor)
                continue
            bound = self.image.hooks.get(ref_key(hook))
            if bound is None or valor is None:
                # un temporal 'R?' que vale null: nada que destruir (A09)
                continue
            self._destruir(bound, Pointer(Cell(valor), mut=True),
                           hook.owner_type)
            if self.trace:
                self.emit("[mem] drop temporal")

    def _destruir(self, bound, puntero, dueno: str, *,
                  ln: int = 0, col: int = 0) -> None:
        """Corre el ``__free__`` de ``dueno``. Si lanza, el programa termina
        con RT021: un destructor nunca puede lanzar.

        Los tres sitios que destruyen (fin de ambito, temporal, ``free``)
        pasan por aqui para que la regla no dependa de por donde murio el
        valor. Sin ella, un ``__free__`` que lanzaba durante el desenrollado
        REEMPLAZABA al ``throw`` en curso: el ``catch`` recibia el segundo y
        el primero se perdia sin rastro.
        """
        try:
            self.call_function(bound[0], bound[1], [puntero], ln=ln, col=col)
        except Thrown as lanzado:
            error = DestructorThrewError(
                f"el __free__ de '{dueno}' lanzó "
                f"{format_value(lanzado.value)}: un destructor nunca puede "
                "lanzar. Si liberar puede fallar, registra el fallo y deja "
                "que el __free__ termine normalmente",
                ln=lanzado.ln or ln, col=lanzado.col or col,
            )
            if lanzado.ln:
                # la posicion es la del 'throw', en el archivo del __free__
                self.set_error_unit(error, lanzado.unit)
            raise error from None

    def _destruir_por_tipo(self, valor, *, ln: int = 0, col: int = 0) -> None:
        """DESTRUIR POR TIPO (el 'drop glue'): ``valor`` muere, y lo que
        corre lo decide su tipo CONCRETO, que aqui se lee del valor.

        La misma regla con que el frontend aplana los drops de un tipo que
        conoce (``scope_resolver._aplanar_drops``), para lo que el frontend no
        puede aplanar (``Drop.by_type``):

        - si el tipo declara ``__free__``, corre ese, y se hace cargo de sus
          campos;
        - si no, sus campos, del ultimo al primero;
        - un BLOQUE de ``mem`` (el de un campo, o uno que se suelta) destruye
          sus celdas no vacias, de la ultima a la primera, y las deja
          liberadas.

        Con una PILA y no con recursion: una lista enlazada de bloques puede
        ser larga, y la pila de Python no.
        """
        pendientes = [valor]
        while pendientes:
            v = pendientes.pop()
            if isinstance(v, StructValue):
                bound = self.image.hooks.get((v.type_name, self._free_kind, ""))
                if bound is not None:
                    self._destruir(bound, Pointer(Cell(v), mut=True),
                                   v.type_name, ln=ln, col=col)
                    continue
                # apilados en orden: el ULTIMO campo sale primero
                for celda in v.fields.values():
                    if celda.state is CellState.LIVE:
                        pendientes.append(celda.value)
            elif isinstance(v, EnumValue):
                for celda in v.fields:
                    if celda.state is CellState.LIVE:
                        pendientes.append(celda.value)
            elif isinstance(v, Block):
                for celda in v.cells:
                    if celda.state is CellState.LIVE:
                        if celda.value is not None:
                            pendientes.append(celda.value)
                        celda.free()

    def destruir_global(self, globales: Frame, nombre: str, *,
                        ln: int = 0, col: int = 0) -> None:
        """Destruye la variable global ``nombre`` al terminar el programa (la
        llama ``interpreter._destruir_globales``, en orden inverso).

        Una global movida (``return move g;``) o ya liberada no tiene nada que
        destruir: es la misma pregunta al estado de la celda que se hace al
        cerrar un bloque. Tras destruirla, la celda queda LIBERADA: si el
        destructor de otra global la leyera después, es un uso tras ``free``
        que se dice, no un valor muerto que se lee en silencio."""
        cell = globales.cells.get(nombre)
        if cell is None or cell.state is not CellState.LIVE:
            return
        if not self._tiene_destructor(cell.value):
            return
        self._destruir_por_tipo(cell.value, ln=ln, col=col)
        cell.free()
        if self.trace:
            self.emit(f"[mem] drop global '{nombre}' (fin del programa)")

    def _tiene_destructor(self, valor) -> bool:
        """¿Destruir ``valor`` por su tipo correría algún ``__free__``?

        Es la pregunta de ``type_service.owns_resources`` hecha sobre el valor
        y no sobre el tipo, porque al terminar el programa el intérprete no
        tiene la lista que el frontend arma para un bloque. Recorre lo mismo
        que ``_destruir_por_tipo``: un puntero no es dueño (no se sigue) y un
        bloque de ``mem`` solo cuenta dentro de un campo (es el almacenamiento
        de un contenedor); en una variable es un puntero."""
        if not isinstance(valor, (StructValue, EnumValue)):
            return False
        pendientes = [valor]
        while pendientes:
            v = pendientes.pop()
            if isinstance(v, StructValue):
                if (v.type_name, self._free_kind, "") in self.image.hooks:
                    return True
                for celda in v.fields.values():
                    if celda.state is CellState.LIVE:
                        pendientes.append(celda.value)
            elif isinstance(v, EnumValue):
                for celda in v.fields:
                    if celda.state is CellState.LIVE:
                        pendientes.append(celda.value)
            elif isinstance(v, Block):
                for celda in v.cells:
                    if celda.state is CellState.LIVE and celda.value is not None:
                        pendientes.append(celda.value)
        return False

    #: las expresiones que producen un valor NUEVO, que es de la llamada que
    #: lo recibe: si un argumento posterior lanza, nadie lo recibio y muere.
    _FRESCOS = frozenset(("struct_literal", "call", "move_expr", "cast_expr"))

    #: las expresiones cuyo valor NADIE MAS tiene: un literal recien creado y
    #: el resultado de una llamada (que ya es una copia o algo transferido:
    #: ver '_stmt_return'; los intrinsecos entregan valores nuevos o sacados
    #: con 'mem.take'). Ligarlas no necesita otra copia, y copiar un 'Vector'
    #: copia su bloque entero: 'var Vector<int> c = v.get(0);' lo copiaba DOS
    #: veces.
    _NUEVOS = frozenset(("struct_literal", "call"))

    def _ligado(self, expr, valor):
        """El valor que se LIGA a un nombre, a un campo o a un elemento:
        una copia, salvo que sea nuevo (``_NUEVOS``)."""
        if expr.WhichOneof("node") in self._NUEVOS:
            return valor
        return copy_on_bind(valor)

    def _argumentos(self, exprs, frame: Frame) -> list:
        """Los valores de ``exprs``, en orden. Si uno LANZA, los ya evaluados
        que eran nuevos (un literal, un resultado, un ``move``) se destruyen
        por su tipo antes de seguir: ``usa(R{...}, falla())`` no le entrega el
        ``R`` a nadie. Es lo que hace la VM con sus temporales frescos."""
        valores: list = []
        try:
            for e in exprs:
                valores.append(self.eval_expr(e, frame))
        except Thrown:
            for e, v in reversed(list(zip(exprs, valores))):
                if e.WhichOneof("node") in self._FRESCOS:
                    self._destruir_por_tipo(v, ln=e.ln, col=e.col)
            raise
        return valores

    def _registrar_temporal(self, valor, hook_ref, por_tipo: bool = False) -> None:
        """Apila un valor sin dueno para destruirlo al cerrar la sentencia:
        con su ``__free__``, o POR SU TIPO (``hook`` None)."""
        if hook_ref.owner_type:
            self._temporales.append((valor, hook_ref))
        elif por_tipo:
            self._temporales.append((valor, None))

    def _stmt_block(self, stmt, frame: Frame) -> None:
        self._exec_block(stmt.block, Frame(parent=frame))

    def _stmt_var_decl(self, stmt, frame: Frame) -> None:
        vd = stmt.var_decl
        # Sin valor no llega: 'var T x;' es SEM040. Un .phir anterior a esa
        # regla todavia puede traerlo, y entonces vale 'null', como antes.
        value = self._ligado(vd.value, self.eval_expr(vd.value, frame)) \
            if vd.HasField("value") else None
        value = self._as_declared(self.unit, vd.type_id, value)
        # ...misma regla que en los parámetros: ligar un struct a un nombre
        # nuevo lo COPIA. El único tipo que refiere a otro sitio es 'ptr'.
        frame.define(vd.name, Cell(value, name=vd.name))

    def _stmt_type_decl(self, stmt, frame: Frame) -> None:
        td = stmt.type_decl
        value: Any = TypeValue(td.name)
        if td.HasField("value"):
            value = self.eval_expr(td.value, frame)
        frame.define(td.name, Cell(value, name=td.name))

    def _stmt_if(self, stmt, frame: Frame) -> None:
        node = stmt.if_stmt
        self._exec_if(node, frame)

    def _condicion(self, expr, frame: Frame) -> Any:
        """La condición de un ``if``/``while``: sus temporales con destructor
        mueren al terminar de evaluarla (el final de la expresión completa,
        como en C++), no al terminar la sentencia. En un ``while`` se
        acumulaban uno por vuelta hasta salir del bucle."""
        marca = len(self._temporales)
        valor = self.eval_expr(expr, frame)
        if len(self._temporales) > marca:
            self._soltar_temporales(marca)
        return valor

    def _exec_if(self, node, frame: Frame) -> None:
        if self._condicion(node.condition, frame):
            self._exec_block(node.then_block, Frame(parent=frame))
        elif node.WhichOneof("else_branch") == "else_block":
            self._exec_block(node.else_block, Frame(parent=frame))
        elif node.WhichOneof("else_branch") == "else_if":
            self._exec_if(node.else_if, frame)

    def _stmt_while(self, stmt, frame: Frame) -> None:
        node = stmt.while_stmt
        while self._condicion(node.condition, frame):
            try:
                self._exec_block(node.body, Frame(parent=frame))
            except _Break:
                break
            except _Continue:
                continue

    def _stmt_match(self, stmt, frame: Frame) -> None:
        node = stmt.match_stmt
        subject = self.eval_expr(node.subject, frame)
        optional = self._es_opcional(node.subject)
        for arm in node.cases:
            propio = Frame(parent=frame)
            if optional:
                # sujeto 'T?': 'case null' mira el SUJETO, sin desreferenciar
                # (en un 'T ptr?' es el puntero el que puede ser null), y
                # ninguna otra rama encaja con null
                if self._es_null(arm.pattern):
                    if subject is None:
                        self.exec_stmt(arm.body, propio)
                        return
                    continue
                if subject is None:
                    continue
            if arm.binds:
                # 'case v': liga el contenido tal cual —sin copiarlo: es el
                # del sujeto, PRESTADO, como el payload de 'case E.A(x)'—
                nombre = arm.pattern.identifier.name
                propio.define(nombre, Cell(subject, name=nombre))
                self.exec_stmt(arm.body, propio)
                return
            if self._encaja(arm.pattern, subject, frame, propio):
                self.exec_stmt(arm.body, propio)
                return

    def _es_opcional(self, expr) -> bool:
        """¿El tipo ESTATICO de ``expr`` es un ``T?`` (``error T?`` incluido)?
        Lo dice el HIR (``Expr.type_id``); sin tipo, no se supone."""
        if not expr.type_id:
            return False
        tipos = self.unit.module.types
        if expr.type_id >= len(tipos):
            return False
        tipo = tipos[expr.type_id]
        while tipo.kind == _TK_ERROR and tipo.HasField("inner"):
            tipo = tipo.inner
        return tipo.kind == _TK_NULLABLE

    @staticmethod
    def _es_null(patron) -> bool:
        return patron.WhichOneof("node") == "literal" \
            and patron.literal.kind == "null"

    def _encaja(self, patron, subject, frame: Frame, propio: Frame) -> bool:
        """¿El patrón de una rama describe a ``subject``?

        Dos clases de patrón. La corriente es una EXPRESIÓN que se evalúa y se
        compara (``case 0``, ``case Color.ROJO``). La otra DESESTRUCTURA una
        variante (``case Nodo.Literal(v)``): ahí el patrón no se evalúa —sus
        argumentos son nombres que se van a LIGAR, no valores que leer—, se
        compara la variante y, si coincide, el payload entra en el frame de la
        rama. Que las dos formas se escriban igual es lo que evitó tener que
        inventar sintaxis de patrones.
        """
        ctor = self._constructor_de(patron, frame)
        if ctor is None:
            # el sujeto se DESREFERENCIA solo también con un patrón de VALOR:
            # 'match (p)' con 'p: int ptr' (o un enum sin payload) compara lo
            # apuntado; antes comparaba el puntero y no coincidía nunca
            subject = self._pointee(subject, ln=patron.ln, col=patron.col)
            # 'case Forma.Punto' (variante sin datos de un enum suma): el
            # loader crea UN 'EnumValue' por variante y nada lo copia (no
            # tiene campos), asi que '==' de Python —la identidad— compara la
            # VARIANTE. No pasa por el '__eq__' del enum: un 'match' elige la
            # forma, no la igualdad que el programa haya declarado.
            return self.eval_expr(patron, frame) == subject
        # DEREF IMPLICITO, igual que en '.campo': un arbol recursivo se
        # escribe con punteros ('Suma(Expr ptr, Expr ptr)'), asi que el sujeto
        # de un match casi siempre LLEGA como puntero. Exigir un deref
        # explicito haria imposible escribir el caso que motiva los tipos
        # suma.
        subject = self._pointee(subject, ln=patron.ln, col=patron.col)
        if not isinstance(subject, EnumValue) or \
                subject.variant != ctor.variant or \
                subject.enum_name != ctor.enum_name:
            return False
        for arg, celda in zip(patron.call.args, subject.fields):
            if arg.WhichOneof("node") == "identifier":
                # se liga la CELDA, no una copia: mutar el payload dentro de
                # la rama se ve fuera, igual que con un campo de struct.
                propio.define(arg.identifier.name, celda)
        return True

    @staticmethod
    def _pointee(value: Any, *, ln: int, col: int) -> Any:
        """Lo que hay DETRAS de un ``E ptr``: el deref implicito de ``match``
        y de ``.campo``.

        Un ``E ptr`` tiene dos formas en ejecucion: el prestamo de una celda
        (``&x``, ``&b[0]``) y un BLOQUE de ``mem.reserve``. El bloque es su
        elemento 0, igual que ``&b[0]``: antes solo se seguia el prestamo, y un
        ``match`` sobre un nodo reservado con ``mem`` no entraba en ninguna
        rama ni decia nada (un arbol calculaba 0)."""
        if isinstance(value, Pointer):
            return value.deref(ln=ln, col=col)
        if isinstance(value, Block):
            return value.element(0, ln=ln, col=col).read(ln=ln, col=col)
        return value

    def _constructor_de(self, patron, frame: Frame):
        """El :class:`VariantCtor` que nombra un patrón, o ``None``.

        Se resuelve SIN evaluar los argumentos: evaluarlos es justo lo que no
        se puede hacer, porque todavía no están ligados.
        """
        if patron.WhichOneof("node") != "call":
            return None
        try:
            valor = self._eval_callee(patron.call.callee, frame)
        except SuriaXRuntimeError:
            return None
        return valor if isinstance(valor, VariantCtor) else None

    def _stmt_return(self, stmt, frame: Frame) -> None:
        node = stmt.return_stmt
        if not node.HasField("value"):
            raise _Return(None)
        value = self.eval_expr(node.value, frame)
        # DEVOLVER UN VALOR TRANSFIERE SU PROPIEDAD. Sin esto, el drop del
        # bloque destruiria lo que el llamador acaba de recibir. Solo aplica a
        # un nombre LOCAL: una global se devuelve prestada, no entregada.
        # Vale igual para un campo ('return a.b'): sin esto, el drop del
        # bloque bajaria a 'a.b' y destruiria lo que el llamador recibio.
        # 'transfers' lo decidio el frontend: solo es cierto si el valor
        # POSEE recursos. Devolver un 'int', o un campo de un receptor
        # PRESTADO, no transfiere nada — y marcarlo invalidaria un valor ajeno.
        cell = self._ruta_local(node.value, frame) if node.transfers else None
        if cell is not None and cell.state is CellState.LIVE:
            # 'move_out' es la API que comparten los dos backends de memoria
            # (el nativo expone 'state' como solo lectura).
            cell.move_out(ln=stmt.ln, col=stmt.col)
        elif node.value.WhichOneof("node") not in self._NUEVOS:
            # DEVOLVER POR VALOR COPIA, igual que ligar a un nombre o pasar
            # por parametro. Sin esto el llamador recibia el MISMO objeto que
            # seguia guardado donde se leyo: 'dame().n = 5' cambiaba la global
            # que 'dame' devolvio, y 'v.get(0).push(8)' el vector guardado en
            # 'v'. Lo transferido (un local que se mueve, arriba) y lo recien
            # creado no tienen a nadie con quien compartir: no se copian.
            value = copy_on_bind(value)
        raise _Return(value)

    def _ruta_local(self, expr, frame: Frame) -> Optional[Cell]:
        """La celda de una ruta ESTATICA (``a`` o ``a.b.c``) cuya raiz es un
        binding de esta llamada, o ``None``.

        Exigir que la raiz sea local no es un detalle: marcar como movida la
        celda de una global la dejaria inservible para el resto del programa.
        Una global se presta, no se entrega.
        """
        partes = []
        nodo = expr
        while True:
            which = nodo.WhichOneof("node")
            if which == "identifier":
                partes.append(nodo.identifier.name)
                break
            if which != "member":
                return None
            partes.append(nodo.member.member)
            nodo = nodo.member.obj
        partes.reverse()
        cell = self._celda_local(frame, partes[0])
        for campo in partes[1:]:
            if cell is None or cell.state is not CellState.LIVE:
                return None
            valor = cell.value
            if not isinstance(valor, StructValue):
                return None
            cell = valor.fields.get(campo)
        return cell

    def _celda_local(self, frame: Frame, name: str):
        """La celda de ``name`` si vive en ESTA llamada, no en el frame global.

        La distincion importa: marcar una global como movida al devolverla la
        dejaria inservible para el resto del programa."""
        globales = self.unit.globals_frame if self.unit is not None else None
        actual = frame
        while actual is not None and actual is not globales:
            cell = actual.cells.get(name)
            if cell is not None:
                return cell
            actual = actual.parent
        return None

    def _stmt_break(self, stmt, frame: Frame) -> None:
        raise _Break()

    def _stmt_continue(self, stmt, frame: Frame) -> None:
        raise _Continue()

    def _expr_move(self, expr, frame: Frame) -> Any:
        """``move x`` como EXPRESION: LEE el valor y luego invalida el origen.

        El orden importa: leer primero es lo que distingue esta forma de la
        sentencia. Una celda movida no se puede leer (``RT001``), así que
        invalidar antes se llevaría por delante el valor que hay que entregar.

        El valor se devuelve **sin copiar**: es el mismo objeto, que es
        justamente lo que significa transferirlo. Quien lo reciba lo liga tal
        cual — la copia de ``copy_on_bind`` solo aplica a lo que se comparte,
        y aquí no queda nadie con quien compartir.
        """
        target = expr.move_expr.operand
        value = self.eval_expr(target, frame)
        self._invalidar(target, frame, ln=expr.ln, col=expr.col)
        return value

    def _invalidar(self, target, frame: Frame, *, ln: int, col: int) -> None:
        """Marca como MOVIDA la celda que nombra ``target``.

        La comparten la sentencia y la expresión: las dos transfieren, y que
        el drop del bloque respete la transferencia no puede depender de en
        qué posición se escribió el ``move``.
        """
        if target.WhichOneof("node") == "identifier":
            cell = frame.lookup(target.identifier.name, ln=ln, col=col)
            cell.move_out(ln=ln, col=col)
            if self.trace:
                self.emit(f"[mem] move '{cell.name}' (celda invalidada)  "
                          f"{ln}:{col}")
            return
        # forma compuesta ('move p.x'): el CAMPO tiene su propia celda, asi
        # que la transferencia se marca ahi. Sin esto el drop del bloque
        # bajaria a ese campo y destruiria lo que ya se habia entregado.
        cell = self._ruta_local(target, frame)
        if cell is not None:
            cell.move_out(ln=ln, col=col)
            if self.trace:
                self.emit(f"[mem] move campo '{cell.name}' (celda invalidada)  "
                          f"{ln}:{col}")
            return
        # ruta dinamica ('move a[i].x'): sus lecturas si se verifican; el
        # rastreo fino queda para el MIR (mismo criterio que memory_check).
        self.eval_expr(target, frame)

    def _stmt_move(self, stmt, frame: Frame) -> None:
        self._invalidar(stmt.move_stmt.target, frame, ln=stmt.ln, col=stmt.col)

    def _stmt_free(self, stmt, frame: Frame) -> None:
        node = stmt.free_stmt
        value = self.eval_expr(node.target, frame)
        if not isinstance(value, Pointer):
            raise InvalidFreeError(
                f"'free' sobre un valor que no es puntero ({format_value(value)})",
                ln=stmt.ln, col=stmt.col,
            )
        if node.hook.owner_type:
            bound = self.image.hooks.get(ref_key(node.hook))
            # lo apuntado es un 'R?' que vale null: no hay destructor que
            # correr (A09); la celda se libera igual
            if bound is not None and value.cell.value is not None:
                self._destruir(bound, value, node.hook.owner_type,
                               ln=stmt.ln, col=stmt.col)
        value.cell.free(ln=stmt.ln, col=stmt.col)
        if self.trace:
            self.emit(f"[mem] free -> celda '{value.cell.name}'  "
                      f"{stmt.ln}:{stmt.col}")

    def _stmt_expr(self, stmt, frame: Frame) -> None:
        self.eval_expr(stmt.expr_stmt.expr, frame)

    def _stmt_import_binding(self, stmt, frame: Frame) -> None:
        node = stmt.import_binding
        frame.define(node.name, Cell(Namespace(node.lib), name=node.name))

    def _stmt_throw(self, stmt, frame: Frame) -> None:
        expr = stmt.throw_stmt.value
        value = self.eval_expr(expr, frame)
        tipo = self._tipo_de(expr)
        if self._es_desconocido(tipo):
            # 'catch (e) { ...; throw e; }': el tipo de 'e' no se sabe al
            # compilar, pero el valor LLEGÓ con uno. Se relanza con ese —como
            # 'raise' en Python— para que un 'catch (T x)' de más arriba lo
            # siga reconociendo. Antes se relanzaba como "error" y caía en la
            # rama equivocada.
            if expr.WhichOneof("node") == "identifier":
                tipo = frame.lanzado(expr.identifier.name) or tipo
        if expr.WhichOneof("node") not in self._NUEVOS and \
                expr.WhichOneof("node") != "move_expr":
            # lo lanzado lo recibe el 'catch' por VALOR, como un 'return': una
            # copia. Sin ella 'throw g;' le daba al 'catch' la global misma.
            value = copy_on_bind(value)
        if self._user_call is not None and self._is_stdlib(self.unit):
            raise self._thrown_at_user_call(value, tipo)
        raise Thrown(value, ln=stmt.ln, col=stmt.col, tipo=tipo)

    def _thrown_at_user_call(self, value, tipo) -> "Thrown":
        """Un ``throw`` de la STDLIB, situado en la llamada del programa que
        entro en ella (H03): la linea de ``vector.libsrx`` no le dice nada a
        quien llamo a ``v.get(9)``, y sin atrapar el error tiene que nombrar
        SU linea. Si lo lanzado es una excepcion con posicion
        (``linea``/``columna``) que la libreria dejo en 0 porque no la conoce
        (``IndiceFueraDeRango`` de ``Vector``), se rellena con la misma. Una
        posicion distinta de 0 ya la puso quien la sabia (un ``catch`` que
        relanza): no se toca."""
        caller, ln, col = self._user_call
        if isinstance(value, StructValue):
            line = value.fields.get("linea")
            column = value.fields.get("columna")
            if line is not None and column is not None \
                    and line.value == 0 and column.value == 0:
                line.write(ln)
                column.write(col)
        return Thrown(value, ln=ln, col=col, tipo=tipo, unit=caller)

    @staticmethod
    def _es_desconocido(tipo) -> bool:
        """¿Es la clave del tipo 'error' a secas (lo que no se sabe)?"""
        global _ERROR_KIND
        if _ERROR_KIND is None:
            from V0.src.HIR.stubs import load_hir_pb2
            _ERROR_KIND = load_hir_pb2().TypeKind.Value("ERROR")
        return tipo is None or (tipo[0] == _ERROR_KIND and tipo[3] is None)

    def _stmt_expect(self, stmt, frame: Frame) -> None:
        """``expect (condicion) [bloque]``: si no se cumple, la prueba termina
        (:class:`ExpectFallido`); si se cumple, corre su bloque y sigue."""
        node = stmt.expect_stmt
        previo = (self._expect_expr, self._expect_valores)
        self._expect_expr, self._expect_valores = node.condition, None
        try:
            cumple = self.eval_expr(node.condition, frame)
            valores = self._expect_valores
        finally:
            self._expect_expr, self._expect_valores = previo
        if not cumple:
            raise ExpectFallido(node.text, ln=stmt.ln, col=stmt.col, valores=valores)
        if node.HasField("body"):
            self._exec_block(node.body, Frame(parent=frame))

    def _stmt_try(self, stmt, frame: Frame) -> None:
        node = stmt.try_stmt
        if not node.HasField("finally_block"):
            self._try_catch(stmt, frame)
            return
        # 'finally': corre al salir por CUALQUIER camino. Los errores
        # fatales (RTxxx que no son del programa) no lo corren: terminan el
        # programa, como un proceso que muere.
        try:
            self._try_catch(stmt, frame)
        except (Thrown, ExcepcionDelPrograma) as en_vuelo:
            self._correr_finally(stmt, frame, en_vuelo)
            raise
        except (_Return, _Break, _Continue, ExpectFallido):
            # un 'expect' fallido sale como un salto: no lo atrapa nadie,
            # pero el 'finally' corre
            self._correr_finally(stmt, frame, None)
            raise
        self._correr_finally(stmt, frame, None)

    def _correr_finally(self, stmt, frame: Frame, en_vuelo) -> None:
        """El bloque ``finally``. Si lanza mientras ``en_vuelo`` ya viajaba,
        el programa termina con RT022: el ``catch`` de afuera solo puede
        recibir una excepcion, y la primera se perderia sin rastro."""
        bloque = stmt.try_stmt.finally_block
        if en_vuelo is None:
            self._exec_block(bloque, Frame(parent=frame))
            return
        try:
            self._exec_block(bloque, Frame(parent=frame))
        except (Thrown, ExcepcionDelPrograma) as otra:
            primera = en_vuelo if isinstance(en_vuelo, Thrown) \
                else self._como_lanzado(en_vuelo)
            segunda = otra if isinstance(otra, Thrown) else self._como_lanzado(otra)
            error = FinallyThrewError(
                f"el 'finally' lanzó {format_value(segunda.value)} mientras ya "
                f"viajaba {format_value(primera.value)}: un 'finally' no puede "
                "lanzar durante un desenrollado. Si limpiar puede fallar, "
                "registra el fallo y deja que el 'finally' termine",
                ln=segunda.ln or stmt.ln, col=segunda.col or stmt.col,
            )
            if segunda.ln:
                self.set_error_unit(error, segunda.unit)
            raise error from None

    def _try_catch(self, stmt, frame: Frame) -> None:
        node = stmt.try_stmt
        # el depurador cuenta los 'try' que pueden atrapar algo: asi sabe,
        # cuando se lanza un error, si alguien lo espera.
        vigila = self.depurador is not None and len(node.catches) > 0
        try:
            if vigila:
                self.depurador.entra_try()
            try:
                self._exec_block(node.try_block, Frame(parent=frame))
            finally:
                if vigila:
                    self.depurador.sale_try()
        except (Thrown, ExcepcionDelPrograma) as fallo:
            # una excepcion del runtime (EXCxxx) entra por las MISMAS ramas
            # que un 'throw': se convierte aqui, en el unico sitio que sabe
            # que alguien quiere atraparla. Si ninguna rama la acepta, el
            # 'raise' de abajo relanza la ORIGINAL y conserva su codigo.
            thrown = fallo if isinstance(fallo, Thrown) \
                else self._como_lanzado(fallo)
            for rama in node.catches:
                if not self._atrapa(rama, thrown):
                    continue
                # el binding de la rama vive SOLO en el scope de su bloque
                catch_frame = Frame(parent=frame)
                catch_frame.define(rama.name,
                                   Cell(thrown.value, name=rama.name))
                catch_frame.lanzados = {rama.name: thrown.tipo}
                if self.trace:
                    self.emit(f"[err] catch '{rama.name}' = "
                              f"{format_value(thrown.value)}  "
                              f"{stmt.ln}:{stmt.col}")
                self._exec_block(rama.block, catch_frame)
                return
            # ninguna rama sabe manejarlo: sigue propagandose. Es lo que hace
            # util filtrar por tipo — un 'catch' que no entiende el fallo no
            # se lo queda.
            raise

    @staticmethod
    def _como_lanzado(fallo: ExcepcionDelPrograma) -> "Thrown":
        """La excepcion del runtime como el valor que la libreria
        ``excepciones`` declara: ``excepciones.DivisionPorCero{mensaje,
        linea, columna}``. La clave de tipo es la CANONICA (la del export de
        la libreria), la misma que el HIR escribe en un ``catch
        (exc.DivisionPorCero e)`` aunque el import use otro alias."""
        global _NOMINAL_KIND
        if _NOMINAL_KIND is None:
            from V0.src.HIR.stubs import load_hir_pb2
            _NOMINAL_KIND = load_hir_pb2().TypeKind.Value("NOMINAL")
        nombre = f"excepciones.{fallo.tipo_excepcion}"
        valor = StructValue(nombre, {
            "mensaje": Cell(fallo.message, name="mensaje"),
            "linea": Cell(fallo.ln, name="linea"),
            "columna": Cell(fallo.col, name="columna"),
        })
        return Thrown(valor, ln=fallo.ln, col=fallo.col,
                      tipo=(_NOMINAL_KIND, nombre, False, None, ()),
                      unit=fallo.unit)

    def _atrapa(self, rama, thrown: "Thrown") -> bool:
        """¿La rama ``catch`` acepta lo que se lanzó?

        Sin tipo declarado, cualquiera. Con tipo, se compara el tipo ESTATICO
        del valor lanzado —el que la Semántica anotó en la expresión del
        ``throw`` y viaja en el HIR— con el de la rama, entero y canónico. Es
        lo que hace la VM de C++ (una etiqueta por tipo).

        Antes se miraba el VALOR en ejecución, y eso confundía dos cosas: un
        ``char`` es aquí una cadena de longitud 1, así que ``catch (str s)``
        atrapaba un ``char`` y ``catch (char c)`` atrapaba ``"y"``; y un tipo
        nominal se comparaba por su nombre CORTO, así que ``catch (b.Error e)``
        atrapaba un ``a.Error`` de otra librería.

        Si el HIR no trae el tipo (``type_id`` 0), queda la prueba dinámica
        de antes como respaldo.
        """
        if not rama.HasField("type"):
            return True
        esperado = type_key(rama.type)
        if thrown.tipo is not None and esperado is not None:
            return thrown.tipo == esperado
        return self._es_de_tipo(thrown.value, rama.type)

    def _es_de_tipo(self, valor: Any, tipo) -> bool:
        """¿``valor`` es del tipo ``tipo``? (prueba DINAMICA, solo para catch)

        Es la unica parte del intérprete que pregunta el tipo de un valor: en
        todo lo demas el frontend ya decidió. Aqui no puede, porque lo que
        lanzo el ``throw`` se sabe en ejecucion.
        """
        kind = tipo.kind
        if kind == _TK_NOMINAL:
            nombre = tipo.name.rsplit(".", 1)[-1]
            if isinstance(valor, StructValue):
                return valor.type_name.rsplit(".", 1)[-1] == nombre
            if isinstance(valor, EnumValue):
                return valor.enum_name.rsplit(".", 1)[-1] == nombre
            return False
        if kind == _TK_INT:
            return isinstance(valor, int) and not isinstance(valor, bool)
        if kind == _TK_STR:
            return isinstance(valor, str)
        if kind == _TK_BOOL:
            return isinstance(valor, bool)
        if kind == _TK_FLOAT:
            return isinstance(valor, float)
        if kind == _TK_CHAR:
            return isinstance(valor, str) and len(valor) == 1
        return False

    # ------------------------------------------------------------------ #
    # expresiones
    # ------------------------------------------------------------------ #
    def eval_expr(self, expr, frame: Frame) -> Any:
        self._tick(expr.ln, expr.col)
        which = expr.WhichOneof("node")
        handler = self._expr_dispatch.get(which)
        if handler is None:
            raise UnsupportedNodeError(
                f"expresión '{which}' sin soporte de ejecución",
                ln=expr.ln, col=expr.col,
            )
        valor = handler(expr, frame)
        # un valor recien producido que POSEE recursos y que nadie recibe se
        # apila para destruirlo al cerrar la sentencia. Quien marco el nodo fue
        # el frontend; aqui solo se obedece.
        if which == "call":
            self._registrar_temporal(valor, expr.call.temp_drop,
                                     expr.call.temp_by_type)
        elif which == "struct_literal":
            self._registrar_temporal(valor, expr.struct_literal.temp_drop,
                                     expr.struct_literal.temp_by_type)
        return valor

    def _expr_literal(self, expr, frame: Frame) -> Any:
        lit = expr.literal
        which = lit.WhichOneof("value")
        if which is None:
            return None  # 'null'
        return getattr(lit, which)

    def _expr_interp(self, expr, frame: Frame) -> str:
        parts: List[str] = []
        for part in expr.interp.parts:
            if part.WhichOneof("part") == "text":
                parts.append(part.text)
            else:
                valor = self.eval_expr(part.expr, frame)
                tipo = (self.unit.module.types[part.expr.type_id]
                        if part.expr.type_id else None)
                texto = self._texto(valor, tipo, self.unit, repr_=part.repr)
                if part.spec:
                    texto = _con_formato(valor, tipo, texto, part.spec)
                parts.append(texto)
        return "".join(parts)

    # ------------------------------------------------------------------ #
    # un valor escrito con su TIPO: el nombre de una variante
    # ------------------------------------------------------------------ #
    def _texto(self, valor: Any, tipo, unidad, *, repr_: bool = False,
               mapa: Optional[dict] = None) -> str:
        """``format_value`` sabiendo el tipo estático del valor.

        Un item de un enum estilo C es un entero en ejecución (``Color.Verde``
        vale 1, ``OK = 200`` vale 200): con el tipo se escribe su NOMBRE,
        igual que una variante con payload (``Circulo(2.5)``). La VM hace lo
        mismo con la tabla de nombres del MIR. Cuando el tipo estático no
        describe el valor (un ``T`` de un genérico), decide el valor:
        ver :meth:`_value_text`.

        Con ``repr_`` (``{x!r}``) se escribe la REPRESENTACION: una cadena con
        sus comillas y escapes, un ``char`` entre apostrofes y un enum con su
        tipo (``Color.Verde``). Un struct se escribe siempre asi, con sus
        campos en el orden declarado y cada uno en su representacion
        (``Punto{x: 1, nombre: "a"}``), como el ``str`` de Python que por
        defecto es el ``repr``.

        ``mapa`` lleva los parametros de tipo del struct que se esta
        escribiendo (``T`` -> ``(tipo, unidad)``): el campo ``T v`` de un
        ``Caja<Color>`` se escribe como un ``Color``.
        """
        if valor is None:
            return "null"
        if tipo is not None:
            global _KINDS_TEXTO
            if _KINDS_TEXTO is None:
                from V0.src.HIR.stubs import load_hir_pb2
                k = load_hir_pb2().TypeKind
                _KINDS_TEXTO = (k.Value("ERROR"), k.Value("NULLABLE"), k.Value("NOMINAL"))
            error, nulable, nominal = _KINDS_TEXTO
            while tipo.kind == error and tipo.HasField("inner"):
                tipo = tipo.inner
            if tipo.kind == nulable and tipo.HasField("inner"):
                tipo = tipo.inner
            if tipo.kind == nominal and mapa and not tipo.args and tipo.name in mapa:
                tipo, unidad = mapa[tipo.name]
                return self._texto(valor, tipo, unidad, repr_=repr_)
            if repr_ and tipo.kind == _TK_STR:
                return _cadena_repr(valor, '"')
            if repr_ and tipo.kind == _TK_CHAR:
                return _cadena_repr(valor, "'")
            if tipo.kind != nominal:
                # un tipo concreto que no es nominal ('int', un puntero...)
                # manda: 'var int n = Color.VERDE;' escribe 1, no VERDE
                return format_value(valor)
            if tipo.kind == nominal:
                enum = self._enum_de(tipo.name, unidad)
                if enum is not None:
                    suya, decl = enum
                    prefijo = f"{decl.name}." if repr_ else ""
                    if isinstance(valor, int) and not isinstance(valor, bool):
                        for nombre, v in suya.enum_values[decl.name].items():
                            if v == valor and not isinstance(v, VariantCtor):
                                return prefijo + nombre
                    if isinstance(valor, EnumValue):
                        # un enum GENERICO ('Res<int, str>'): su payload 'T'
                        # se escribe como el argumento que lo sustituye
                        propio = {}
                        for param, arg in zip(decl.type_params, tipo.args):
                            if mapa and arg.kind == nominal and not arg.args \
                                    and arg.name in mapa:
                                propio[param] = mapa[arg.name]
                            else:
                                propio[param] = (arg, unidad)
                        for item in decl.items:
                            if item.name != valor.variant:
                                continue
                            if not item.payload_type_ids:
                                # variante SIN datos de un enum suma: su nombre
                                return prefijo + valor.variant
                            campos = [
                                self._texto(c.value, suya.module.types[t], suya,
                                            repr_=repr_, mapa=propio)
                                for c, t in zip(valor.fields, item.payload_type_ids)]
                            return f"{prefijo}{valor.variant}({', '.join(campos)})"
                struct = self._struct_de(tipo.name, unidad)
                if struct is not None and isinstance(valor, StructValue):
                    suya, decl = struct
                    propio = {}
                    for param, arg in zip(decl.type_params, tipo.args):
                        if mapa and arg.kind == nominal and not arg.args \
                                and arg.name in mapa:
                            propio[param] = mapa[arg.name]
                        else:
                            propio[param] = (arg, unidad)
                    campos = []
                    for campo in decl.fields:
                        celda = valor.fields.get(campo.name)
                        texto = self._texto(
                            celda.value if celda is not None else None,
                            suya.module.types[campo.type_id], suya,
                            repr_=True, mapa=propio)
                        campos.append(f"{campo.name}: {texto}")
                    corto = valor.type_name.rsplit(".", 1)[-1]
                    return f"{corto}{{{', '.join(campos)}}}"
        # el tipo estatico no describe el valor (es un 'T' de un generico, o
        # no hay tipo): lo dice el VALOR, que sabe de que tipo concreto es
        return self._value_text(valor, unidad, repr_)

    def _value_text(self, value: Any, unit, repr_: bool) -> str:
        """El texto de ``valor`` decidido por el VALOR y no por el tipo
        estatico (A08).

        Dentro de un generico, ``f"{x}"`` con ``x: T`` tiene a ``T`` como tipo
        estatico, y ``T`` no nombra ningun struct ni enum: el cuerpo es UNO
        para todas las instancias. Lo que si sabe de que tipo es, es el valor:
        un struct lleva su nombre, una variante su enum, y un item estilo C es
        un :class:`EnumItem`. Con eso se escribe EXACTAMENTE igual que con el
        tipo concreto: ``P{x: 3, s: "hi"}``, ``Dot``, ``VERDE``,
        ``Ok(ROJO)``. Los campos y el payload se escriben con el tipo que
        declara SU declaracion; si ese tipo es otra vez un parametro (un
        ``Caja<T>`` dentro de un generico), vuelve a decidir el valor.

        Lo que el valor NO distingue es un ``str`` de un ``char`` (aqui los
        dos son una cadena): ``{x!r}`` de un ``T`` primitivo sigue saliendo
        sin comillas, como antes."""
        if isinstance(value, EnumItem):
            return (f"{value.enum_of}." if repr_ else "") + value.variant
        if isinstance(value, EnumValue):
            enum = self._decl_of_value(self._enum_de, "_enums", value.enum_name, unit)
            if enum is not None:
                owner, decl = enum
                prefix = f"{decl.name}." if repr_ else ""
                for item in decl.items:
                    if item.name != value.variant:
                        continue
                    if not item.payload_type_ids:
                        return prefix + value.variant
                    fields_text = [
                        self._texto(c.value, owner.module.types[t], owner,
                                    repr_=repr_)
                        for c, t in zip(value.fields, item.payload_type_ids)]
                    return f"{prefix}{value.variant}({', '.join(fields_text)})"
        if isinstance(value, StructValue):
            found = self._decl_of_value(self._struct_de, "_structs",
                                        value.type_name, unit)
            if found is not None:
                owner, decl = found
                fields_text = []
                for field in decl.fields:
                    cell = value.fields.get(field.name)
                    text = self._texto(
                        cell.value if cell is not None else None,
                        owner.module.types[field.type_id], owner, repr_=True)
                    fields_text.append(f"{field.name}: {text}")
                short = value.type_name.rsplit(".", 1)[-1]
                return f"{short}{{{', '.join(fields_text)}}}"
        return format_value(value)

    def _decl_of_value(self, lookup, table: str, name: str, unit):
        """La declaracion del tipo que lleva un VALOR: la que resuelve
        ``lookup`` (como un tipo escrito en ``unit``) o, si no, la UNICA de
        cualquier unidad con ese nombre corto. Un valor creado dentro de una
        libreria lleva el nombre con que esa libreria lo declara, y el
        f-string que lo escribe puede estar en otra unidad. Con dos
        candidatas no se adivina: ``None``, y se escribe sin tipo."""
        found = lookup(name, unit)
        if found is not None:
            return found
        short = name.rsplit(".", 1)[-1]
        candidates = [v for (alias, n), v in getattr(self, table).items()
                      if n == short]
        return candidates[0] if len(candidates) == 1 else None

    def _struct_de(self, nombre: str, unidad):
        """La declaración del struct que nombra un tipo CANÓNICO (como
        :meth:`_enum_de`)."""
        if self._structs is None:
            self._structs = {}
            for u in [self.image.main, *self.image.units.values()]:
                for d in u.module.items:
                    if d.WhichOneof("node") == "struct_decl":
                        self._structs[(u.alias, d.struct_decl.name)] = (u, d.struct_decl)
        if "." in nombre:
            prefijo, suelto = nombre.rsplit(".", 1)
            for (alias, n), valor in self._structs.items():
                if n == suelto and (alias == prefijo or alias.endswith("." + prefijo)):
                    return valor
            return None
        return (self._structs.get((unidad.alias, nombre))
                or self._structs.get((self.image.main.alias, nombre)))

    def _enum_de(self, nombre: str, unidad):
        """La declaración del enum que nombra un tipo CANÓNICO: suelto es de
        la unidad que lo usa (o del main); ``alias.Nombre`` es de esa
        librería (se compara el último tramo del alias, como el MIR)."""
        if self._enums is None:
            self._enums = {}
            for u in [self.image.main, *self.image.units.values()]:
                for d in u.module.items:
                    if d.WhichOneof("node") == "enum_decl":
                        self._enums[(u.alias, d.enum_decl.name)] = (u, d.enum_decl)
        if "." in nombre:
            prefijo, suelto = nombre.rsplit(".", 1)
            for (alias, n), valor in self._enums.items():
                if n == suelto and (alias == prefijo or alias.endswith("." + prefijo)):
                    return valor
            return None
        return (self._enums.get((unidad.alias, nombre))
                or self._enums.get((self.image.main.alias, nombre)))

    def _expr_identifier(self, expr, frame: Frame) -> Any:
        return frame.lookup(expr.identifier.name, ln=expr.ln,
                            col=expr.col).read(ln=expr.ln, col=expr.col)

    def _expr_unary(self, expr, frame: Frame) -> Any:
        node = expr.unary
        operand = self.eval_expr(node.operand, frame)
        if node.op == "not":
            return not operand
        if node.op == "~":
            if self._es_byte(expr):
                return ~operand & 0xFF   # un byte no tiene signo: 8 bits
            return ~operand   # -x-1: con un int de 64 bits nunca desborda
        return self._arith(-operand)  # '-' (negar INT_MIN también desborda)

    def _receptor(self, method, obj, frame: Frame) -> Any:
        """El primer argumento de ``x.metodo()``.

        Un objeto (un struct, un enum con payload) se COMPARTE tal cual: sus
        campos son celdas, así que es su propio préstamo. Un ESCALAR —un enum
        sin payload es un entero— no tiene campos que compartir: si el método
        lo toma por ``T ptr``, recibe el préstamo de la celda que lo guarda,
        como ``&x``. Antes recibía el valor y ``self[0]`` fallaba (``RT014``).
        """
        valor = self.eval_expr(obj, frame)
        unit, decl = method
        # solo un ESCALAR: un objeto ya es su préstamo, y un puntero YA es
        # un préstamo (envolverlo daría un puntero a un puntero)
        if not isinstance(valor, (int, float, str)) or not decl.params \
                or not self._es_prestamo(unit, decl.params[0]):
            return valor
        which = obj.WhichOneof("node")
        if which == "identifier":
            return Pointer(frame.lookup(obj.identifier.name, ln=obj.ln, col=obj.col), mut=True)
        if which == "member":
            base = self.eval_expr(obj.member.obj, frame)
            return Pointer(self._field_cell(base, obj.member.member, ln=obj.ln, col=obj.col),
                           mut=True)
        return valor

    def _expr_addr_of(self, expr, frame: Frame) -> Pointer:
        node = expr.addr_of
        operand = node.operand
        which = operand.WhichOneof("node")
        if which == "identifier":
            cell = frame.lookup(operand.identifier.name,
                                ln=expr.ln, col=expr.col)
            if self.trace:
                self.emit(f"[mem] &{cell.name} -> ptr"
                          f"{' mutable' if node.mut else ''}  {expr.ln}:{expr.col}")
            return Pointer(cell, mut=node.mut)
        if which == "member":
            base = self.eval_expr(operand.member.obj, frame)
            cell = self._field_cell(base, operand.member.member,
                                    ln=expr.ln, col=expr.col)
            return Pointer(cell, mut=node.mut)
        if which == "index":
            # '&b[i]': el PRESTAMO de un elemento. Solo de un objeto (un
            # struct, un enum con payload): la VM lo presta por su handle y no
            # tiene punteros al interior de un bloque para un escalar. Es lo
            # que usa 'Vector.at'.
            base = self.eval_expr(operand.index.obj, frame)
            idx = self.eval_expr(operand.index.index, frame)
            cell = self._element_cell(base, idx, ln=expr.ln, col=expr.col)
            if isinstance(cell.value, (StructValue, EnumValue)):
                # presta ESE objeto: si el contenedor lo reemplaza o lo saca,
                # el prestamo muere con el (RT003, como en la VM)
                return Pointer(cell, mut=node.mut, target=cell.value)
            raise UnsupportedNodeError(
                "'&' sobre un elemento que no es un objeto: la dirección de "
                "un escalar dentro de un bloque no tiene soporte de ejecución",
                ln=expr.ln, col=expr.col,
            )
        raise UnsupportedNodeError(
            f"'&' sobre '{which}' sin soporte de ejecución",
            ln=expr.ln, col=expr.col,
        )

    @staticmethod
    def _wrap64(value: int) -> int:
        """El ``int`` de suriaX es de 64 bits CON SIGNO: envuelve al desbordar.

        Python no tiene ese límite, así que sin esto el intérprete daba
        9223372036854775808 donde el target web —que sí envuelve, con
        ``BigInt.asIntN(64, …)``— daba el mínimo negativo, y donde una VM
        nativa dará lo mismo que el web. Es el MISMO argumento que ya obligó
        a que ``%`` tome el signo del dividendo: dos targets del mismo
        programa no pueden dar números distintos.

        Y además evitaba un fallo peor: guardar el valor desbordado en una
        celda del backend nativo reventaba con un error de pybind11
        ("Unable to cast Python instance of type int to C++ type"), porque
        ahí una celda es un ``int64_t`` de verdad. Un error del binding no es
        un diagnóstico del lenguaje.
        """
        value &= 0xFFFFFFFFFFFFFFFF
        return value - 0x10000000000000000 if value >= 0x8000000000000000 else value

    @classmethod
    def _arith(cls, value: Any) -> Any:
        """Resultado de una operación aritmética, envuelto si es entero."""
        return cls._wrap64(value) if type(value) is int else value

    def _expr_binary(self, expr, frame: Frame) -> Any:
        node = expr.binary
        op = node.op
        if op == "and":  # corto-circuito: el derecho solo si hace falta
            return bool(self.eval_expr(node.left, frame)) and \
                bool(self.eval_expr(node.right, frame))
        if op == "or":
            return bool(self.eval_expr(node.left, frame)) or \
                bool(self.eval_expr(node.right, frame))
        if op == "??":
            # 'x ?? d': el contenido de 'x' si no es null. El defecto SOLO se
            # evalua si hace falta (cortocircuito, como 'or'): 'x ?? caro()'
            # no llama a 'caro' cuando 'x' tiene valor. Ligar el resultado a
            # un nombre lo copia, como cualquier lectura (la Semantica ya
            # rechazo un contenido con destructor, SEM032).
            valor = self.eval_expr(node.left, frame)
            if valor is not None:
                return valor
            return self.eval_expr(node.right, frame)
        left = self.eval_expr(node.left, frame)
        right = self.eval_expr(node.right, frame)
        if expr is self._expect_expr and op in ("==", "!=", "<", "<=", ">", ">="):
            self._expect_valores = (left, right)
        if op == "+":
            return self._arith(left + right)
        if op == "-":
            return self._arith(left - right)
        if op == "*":
            return self._arith(left * right)
        if op == "/":
            # división entera para ints (idioma 'i / 3 * 3 == i' de los
            # ejemplos); real para floats — el tipado fuerte ya garantizó
            # operandos homogéneos.
            #
            # Dividir por cero es un ERROR solo entre ENTEROS: ahí no hay
            # respuesta y la instrucción del hardware trapea. Entre flotantes
            # sí la hay y está en la norma que el lenguaje declara seguir —
            # IEEE-754 dice '1.0 / 0.0 == +inf'—, así que lanzar ahí inventaba
            # un error donde el target web (y cualquier FPU) daba un valor.
            if right == 0 and isinstance(left, int) \
                    and not isinstance(left, bool):
                raise DivisionByZeroError(
                    "división por cero", ln=expr.ln, col=expr.col)
            if isinstance(left, int) and not isinstance(left, bool):
                # TRUNCA HACIA CERO (como C y como 'i64.div_s', no como el
                # '//' de Python, que redondea hacia abajo): '-7 / 2' es -3,
                # no -4. Es la misma decisión que ya estaba tomada dos casos
                # más abajo para el resto — y tenía que serlo, porque las dos
                # operaciones se sostienen mutuamente: con este cociente y
                # aquel resto se cumple '(a/b)*b + a%b == a', que con el
                # cociente de Python NO se cumplía ('-9' en vez de '-7').
                cociente = abs(left) // abs(right)
                if (left < 0) != (right < 0):
                    cociente = -cociente
                # ...y la división también desborda, en un solo punto:
                # INT_MIN / -1 no cabe en 64 bits con signo.
                return self._wrap64(cociente)
            # IEEE-754 a mano: el '/' de Python lanza tambien entre flotantes,
            # asi que el infinito con signo (y el NaN de '0.0/0.0') se
            # construyen aqui. Es lo que hace la FPU y lo que ya hacia el
            # target web.
            if right == 0:
                if left == 0:
                    return math.nan
                signo = math.copysign(1.0, left) * math.copysign(1.0, right)
                return math.copysign(math.inf, signo)
            return left / right
        if op == "%":
            # resto CON EL SIGNO DEL DIVIDENDO (como C, no como Python):
            # '-7 % 3' es -1, no 2. El backend nativo bajará a la instrucción
            # de resto del hardware, que hace justo esto; si el intérprete
            # usara el '%' de Python, los dos targets darían números distintos
            # para el mismo programa.
            # mismo criterio que la división: entre flotantes, IEEE-754 da
            # NaN y no hay error que reportar.
            if right == 0 and isinstance(left, int) \
                    and not isinstance(left, bool):
                raise DivisionByZeroError(
                    "resto de una división por cero", ln=expr.ln, col=expr.col)
            if isinstance(left, int) and not isinstance(left, bool):
                resto = abs(left) % abs(right)
                return -resto if left < 0 else resto
            # 'fmod(x, 0.0)' lanza en Python; IEEE-754 dice NaN.
            return math.nan if right == 0 else math.fmod(left, right)
        # BITS, sobre enteros de 64 bits con signo. '&', '|' y '^' de dos
        # valores en rango dan un valor en rango (complemento a dos); '<<'
        # envuelve como la maquina y '>>' es aritmetico (conserva el signo),
        # que es lo que hace el '>>' de Python sobre un negativo.
        if op == "&":
            return left & right
        if op == "|":
            return left | right
        if op == "^":
            return left ^ right
        if op in ("<<", ">>"):
            if right < 0 or right > 63:
                raise ShiftOutOfRangeError(
                    f"desplazamiento de {right} bits fuera de [0, 64)",
                    ln=expr.ln, col=expr.col)
            return self._wrap64(left << right) if op == "<<" else left >> right
        if op == "==":
            return self._igual(left, right, expr)
        if op == "!=":
            # la negacion de '==', nunca otra comparacion: con un '__eq__'
            # declarado, 'a != b' es 'not a.__eq__(b)'
            return not self._igual(left, right, expr)
        if op in ("<", "<=", ">", ">="):
            if isinstance(left, (StructValue, EnumValue)):
                # un tipo propio se ordena por su '__cmp__': los cuatro
                # operadores salen del mismo entero
                c = self._dispatch_cmp(left, right, expr)
                left, right = c, 0
            if op == "<":
                return left < right
            if op == "<=":
                return left <= right
            if op == ">":
                return left > right
            return left >= right
        raise UnsupportedNodeError(f"operador binario '{op}' desconocido",
                                   ln=expr.ln, col=expr.col)

    def _hash(self, valor: Any, expr) -> int:
        """El hash de un valor, IGUAL al de la VM (el orden de las claves de
        un diccionario depende de el, y los dos motores lo imprimen igual):

        - ``int``/``bool`` (y un item de un enum estilo C): splitmix64 de sus
          64 bits;
        - ``str`` y ``char``: FNV-1a de 64 bits sobre su UTF-8 (un ``char`` es
          un texto de un caracter aqui, y en la VM se hashea igual);
        - un struct o un enum con payload: su ``__hash__``.
        """
        if isinstance(valor, bool) or (isinstance(valor, int)):
            return _splitmix64(int(valor))
        if isinstance(valor, str):
            return _fnv1a(valor.encode("utf-8"))
        if isinstance(valor, float):
            raise UnsupportedNodeError(
                "un 'float' no tiene hash: NaN no es igual a si mismo",
                ln=expr.ln, col=expr.col)
        if isinstance(valor, FunctionValue):
            # solo llega por un generico ('hash(k)' con K un tipo funcion):
            # fuera de uno, la Semantica lo rechaza (AST006)
            raise UnsupportedNodeError(
                f"un valor funcion ({format_value(valor)}) no tiene hash: no "
                "puede ser clave", ln=expr.ln, col=expr.col)
        tipo = getattr(valor, "type_name", None) or getattr(valor, "enum_name", None)
        bound = self.image.hooks.get(hook_key(tipo, self._hash_kind)) if tipo else None
        if bound is None:
            raise UnsupportedNodeError(
                f"'{tipo}' no define '__hash__'", ln=expr.ln, col=expr.col)
        return self.call_function(bound[0], bound[1], [valor],
                                  ln=expr.ln, col=expr.col)

    def _igual(self, left: Any, right: Any, expr) -> bool:
        """``a == b`` con la semantica del lenguaje: igualdad de VALOR.

        - un struct o un enum con payload con ``__eq__``: lo que diga el hook
          (vale para un enum tambien: antes solo se miraba el struct, y el
          ``__eq__`` de un enum se aceptaba al compilar y no se llamaba);
        - sin ``__eq__``: campo a campo (un enum: la misma variante y su
          payload, valor a valor), recursivo, y cada campo con SU igualdad
          —un campo con ``__eq__`` propio lo usa—. Antes caia a la identidad
          del objeto de Python: ``b = a`` COPIA el struct, y ``a == b`` daba
          ``false`` justo cuando eran iguales;
        - un puntero compara la DIRECCION (la celda), no lo apuntado: es el
          valor del puntero, y seguirlo podria no terminar (una lista
          circular) o confundir dos prestamos de cosas distintas que valen lo
          mismo. Un bloque de ``mem`` en un campo, igual: el interprete no
          sabe cuantas de sus celdas estan en uso (eso lo lleva otro campo,
          por convencion), asi que el contenedor que si lo sabe declara su
          ``__eq__`` (``Vector`` lo hace);
        - lo demas (primitivos, null): la igualdad de Python, que en esos
          valores es la del lenguaje.
        """
        # camino rapido: casi todo '==' es entre primitivos (el tipado fuerte
        # garantiza que el otro lado es del mismo tipo)
        tipo = type(left)
        if tipo is int or tipo is str or tipo is bool or tipo is float:
            return left == right
        if isinstance(left, StructValue):
            if not isinstance(right, StructValue) \
                    or left.type_name != right.type_name:
                return False
            eq = self._dispatch_eq(left.type_name, left, right, expr)
            if eq is not None:
                return eq
            return all(self._igual(celda.value, right.fields[nombre].value, expr)
                       for nombre, celda in left.fields.items()
                       if nombre in right.fields)
        if isinstance(left, EnumValue):
            if not isinstance(right, EnumValue) \
                    or left.enum_name != right.enum_name:
                return False
            eq = self._dispatch_eq(left.enum_name, left, right, expr)
            if eq is not None:
                return eq
            return left.variant == right.variant \
                and len(left.fields) == len(right.fields) \
                and all(self._igual(a.value, b.value, expr)
                        for a, b in zip(left.fields, right.fields))
        if isinstance(left, Pointer):
            return isinstance(right, Pointer) and left.cell is right.cell
        if isinstance(left, Block) or isinstance(right, Block) \
                or isinstance(right, (StructValue, EnumValue, Pointer)):
            return left is right
        return left == right

    def _dispatch_eq(self, tipo: str, left: Any, right: Any,
                     expr) -> Optional[bool]:
        """El ``__eq__`` de ``tipo`` sobre ``left``/``right``; ``None`` si el
        tipo no lo declara (y entonces manda la igualdad de valor)."""
        bound = self.image.hooks.get(hook_key(tipo, self._eq_kind))
        if bound is None:
            return None
        return bool(self.call_function(bound[0], bound[1], [left, right],
                                       ln=expr.ln, col=expr.col))

    def _dispatch_cmp(self, left: Any, right: Any, expr) -> int:
        """``a < b`` (y ``<=``, ``>``, ``>=``) entre dos valores de un tipo
        propio: el entero que devuelve su ``__cmp__``.

        La Semantica ya exigio el hook (AST006 directo, SEM039 a traves de un
        generico), asi que no encontrarlo aqui es un HIR que no salio de este
        frontend: se dice con posicion en vez de comparar dos objetos de
        Python, que daria un orden inventado.
        """
        tipo = left.type_name if isinstance(left, StructValue) else left.enum_name
        otro = getattr(right, "type_name", None) or getattr(right, "enum_name", None)
        if otro != tipo:
            raise UnsupportedNodeError(
                f"comparación de orden entre '{tipo}' y '{otro}'",
                ln=expr.ln, col=expr.col)
        bound = self.image.hooks.get(hook_key(tipo, self._cmp_kind))
        if bound is None:
            raise UnsupportedNodeError(
                f"'{tipo}' no define '__cmp__': no se puede ordenar",
                ln=expr.ln, col=expr.col)
        resultado = self.call_function(bound[0], bound[1], [left, right],
                                       ln=expr.ln, col=expr.col)
        if type(resultado) is not int:
            raise UnsupportedNodeError(
                f"el '__cmp__' de '{tipo}' devolvió "
                f"'{format_value(resultado)}' y tiene que devolver un 'int'",
                ln=expr.ln, col=expr.col)
        return resultado

    def _expr_assignment(self, expr, frame: Frame) -> Any:
        node = expr.assignment
        # Un struct es un VALOR: asignarlo lo COPIA, igual que ligarlo con
        # 'var'. Antes 'b = a; b.v = 99' cambiaba tambien 'a', y
        # 'e.dentro = c' dejaba a 'e' y a 'c' compartiendo el mismo objeto.
        value = self._ligado(node.value, self.eval_expr(node.value, frame))
        target = node.target
        which = target.WhichOneof("node")
        if which == "identifier":
            cell = frame.lookup(target.identifier.name, ln=expr.ln, col=expr.col)
            if node.drops_old:
                self._muere_el_viejo(cell, expr)
            cell.write(value, ln=expr.ln, col=expr.col)
            return value
        if which == "member":
            base = self.eval_expr(target.member.obj, frame)
            cell = self._field_cell(base, target.member.member,
                                    ln=expr.ln, col=expr.col)
            if node.drops_old:
                self._muere_el_viejo(cell, expr)
            cell.write(value, ln=expr.ln, col=expr.col)
            return value
        if which == "index":
            base = self.eval_expr(target.index.obj, frame)
            idx = self.eval_expr(target.index.index, frame)
            # 'v[i] = x' sobre un tipo nominal con hook __index_set__ (o un
            # puntero a él): despacha al hook. El indexado crudo de un bloque
            # sigue por _element_cell.
            despacho = self._hook_de_indexado(base, self._index_set_kind,
                                              ln=expr.ln, col=expr.col)
            if despacho is not None:
                bound, receptor = despacho
                self.call_function(bound[0], bound[1], [receptor, idx, value],
                                   ln=expr.ln, col=expr.col)
                return value
            cell = self._element_cell(base, idx, ln=expr.ln, col=expr.col)
            if node.drops_old:
                self._muere_el_viejo(cell, expr)
            cell.write(value, ln=expr.ln, col=expr.col)
            return value
        raise UnsupportedNodeError(
            f"asignación a '{which}' sin soporte de ejecución",
            ln=expr.ln, col=expr.col,
        )

    def _muere_el_viejo(self, cell, expr) -> None:
        """El valor que tenia un destino que POSEE muere al recibir otro
        (``Assignment.drops_old``). Una celda vacia, movida o liberada no
        tiene nada que destruir. La celda NO se libera: se escribe ya."""
        if cell.state is CellState.LIVE and cell.value is not None:
            self._destruir_por_tipo(cell.value, ln=expr.ln, col=expr.col)

    def _expr_call(self, expr, frame: Frame) -> Any:
        node = expr.call
        callee = node.callee
        # 'hash(x)': nativo o por el '__hash__' del tipo EN EJECUCION (en un
        # generico el frontend no sabe cual es)
        if node.hook.owner_type and node.hook.kind == self._hash_kind:
            receptor = (callee.member.obj
                        if callee.WhichOneof("node") == "member" and not node.args
                        else node.args[0])
            return self._hash(self.eval_expr(receptor, frame), expr)
        # despacho de hook FIJO ya enlazado (print(x) / x.print() / len(x))
        if node.hook.owner_type:
            bound = self.image.hooks.get(ref_key(node.hook))
            if bound is not None:
                # forma 'x.hook(...)': el receptor es el PRIMER argumento y no
                # viaja en 'node.args'. Se detecta por aridad —al cuerpo le
                # falta exactamente un parámetro—, así que vale igual para
                # 'x.print()' (0 argumentos, 1 parámetro) que para un hook del
                # proyecto 'b.__gravity__(dt)' (1 y 2). Antes solo se cubría el
                # caso sin argumentos, y el primer argumento acababa ocupando
                # el sitio del receptor.
                es_miembro = callee.WhichOneof("node") == "member"
                falta_receptor = (es_miembro and
                                  len(node.args) + 1 == len(bound[1].params))
                args = []
                if falta_receptor:
                    # se evalúa ANTES que los argumentos: es el orden en que
                    # está escrito, y el receptor puede tener efectos.
                    args.append(self.eval_expr(callee.member.obj, frame))
                args.extend(self.eval_expr(a, frame) for a in node.args)
                return self.call_function(bound[0], bound[1], args,
                                          ln=expr.ln, col=expr.col)
            # método de usuario 'x.__metodo__(args)' -> dunder (owner, nombre).
            # El receptor va como PRIMER argumento: el struct se COMPARTE (sus
            # campos son celdas), así un método que muta 'x' se propaga al
            # llamante — el mismo modelo que un parámetro 'T ptr mutable'.
            if callee.WhichOneof("node") == "member":
                method = self.image.dunders.get(
                    (node.hook.owner_type, callee.member.member))
                if method is not None:
                    args = [self._receptor(method, callee.member.obj, frame)]
                    args.extend(self._argumentos(node.args, frame))
                    return self.call_function(method[0], method[1], args,
                                              ln=expr.ln, col=expr.col)
            # 'len(s)' sobre un 'str': NATIVO, no lo declara ninguna libreria.
            # Llega como una HookRef con dueño 'str' (la marca el frontend),
            # así que se reconoce por TIPO y no por el nombre de la llamada —
            # una 'fn len' del usuario nunca pasa por aquí.
            # 'print(5)': un PRIMITIVO se escribe como lo escribe un f-string
            # ('{x}'), sin salto de linea, por el mismo canal que
            # '__write__'. Es lo mismo que hace 'print(x)' con 'T: Print' y
            # una instancia primitiva (ver '_call_by_runtime_type').
            if node.hook.kind == self._print_kind and \
                    node.hook.owner_type in _PRINTABLE_PRIMITIVES:
                arg = node.args[0]
                value = self.eval_expr(arg, frame)
                typ = (self.unit.module.types[arg.type_id]
                       if arg.type_id else None)
                intrinsics.REGISTRY["__write__"](self._texto(value, typ,
                                                             self.unit))
                return None
            if node.hook.owner_type == "str" and \
                    node.hook.kind == self._len_kind:
                receptor = (callee.member.obj
                            if callee.WhichOneof("node") == "member"
                            else node.args[0])
                return len(self.eval_expr(receptor, frame))
            # el dueño es un PARAMETRO DE TIPO ('print(x)' o 'x.area()' con
            # 'x: T' y una cota 'T: Print' / 'T: Forma'): lo despacha el tipo
            # que 'T' tenga en esta instancia, igual que 'hash(x)'
            if node.hook.owner_type in self.image.type_params:
                return self._call_by_runtime_type(expr, node, frame)

        callee_value = self._eval_callee(node.callee, frame)
        args = self._argumentos(node.args, frame)
        if isinstance(callee_value, VariantCtor):
            # 'Nodo.Literal(5)' construye el valor de la variante. El payload
            # va en celdas, como los campos de un struct: asi participa del
            # mismo modelo de memoria que todo lo demas.
            if len(args) != callee_value.arity:
                raise NotCallableError(
                    f"'{callee_value.enum_name}.{callee_value.variant}' lleva "
                    f"{callee_value.arity} valor(es), se pasaron {len(args)}",
                    ln=expr.ln, col=expr.col,
                )
            # ...y el payload se liga como un campo: una copia (ver
            # '_expr_struct_literal')
            celdas = [Cell(self._ligado(e, v), name=f"{callee_value.variant}.{i}")
                      for i, (e, v) in enumerate(zip(node.args, args))]
            return EnumValue(callee_value.enum_name, callee_value.variant,
                             celdas)
        if isinstance(callee_value, FunctionValue):
            unit = self.image.main if callee_value.unit_alias == "" \
                else self.image.units[callee_value.unit_alias]
            return self.call_function(unit, callee_value.decl, args,
                                      ln=expr.ln, col=expr.col)
        if isinstance(callee_value, LambdaValue):
            return self.call_lambda(callee_value, args,
                                    ln=expr.ln, col=expr.col)
        if callee_value is None:
            # un '(fn(...) -> R)?' que vale null: como leer un campo por un
            # puntero nulo (la Semantica deja llamarlo, ver 'NotCallableError')
            raise NullDereferenceError(
                "llamada a una funcion que vale null (un '(fn(...) -> R)?' "
                "sin valor)", ln=expr.ln, col=expr.col)
        raise NotCallableError(
            f"'{format_value(callee_value)}' no es invocable",
            ln=expr.ln, col=expr.col,
        )

    def _call_by_runtime_type(self, expr, node, frame: Frame) -> Any:
        """Una llamada que la Semantica comprobo contra una COTA y no contra
        un tipo: ``print(x)`` con ``T: Print`` o ``x.metodo(...)`` con un
        trait de las cotas de ``T``. El cuerpo generico es uno solo para todas
        las instancias, asi que el destino sale del valor: su ``__print__`` o
        su metodo ``(tipo, nombre)``.

        Un primitivo cumple ``Print`` sin hook: se escribe como lo escribe un
        f-string (``{x}``), sin salto de linea, por el mismo canal que
        ``__write__``. Lo que no tiene destino es un error EXPLICITO: la
        Semantica no deberia dejarlo llegar, y si llega no se adivina."""
        callee = node.callee
        es_miembro = callee.WhichOneof("node") == "member"
        receptor = callee.member.obj if es_miembro else node.args[0]
        valor = self.eval_expr(receptor, frame)
        objeto = valor.deref(ln=expr.ln, col=expr.col) \
            if isinstance(valor, Pointer) else valor
        tipo = getattr(objeto, "type_name", None) \
            or getattr(objeto, "enum_name", None)
        if node.hook.kind == self._print_kind:
            if tipo:
                bound = self.image.hooks.get(hook_key(tipo, self._print_kind))
                if bound is not None:
                    return self.call_function(bound[0], bound[1], [valor],
                                              ln=expr.ln, col=expr.col)
            elif isinstance(objeto, (bool, int, float, str)):
                intrinsics.REGISTRY["__write__"](self._texto(objeto, None,
                                                             self.unit))
                return None
            raise UnsupportedNodeError(
                f"'print' sobre un valor de tipo '{tipo or format_value(objeto)}' "
                f"(el '{node.hook.owner_type}' de una cota 'Print') que no "
                "define '__print__'", ln=expr.ln, col=expr.col)
        member = callee.member.member if es_miembro else ""
        method = self.image.dunders.get((tipo, member)) if tipo else None
        if method is None:
            raise UnsupportedNodeError(
                f"'{member}' sobre un valor de tipo "
                f"'{tipo or format_value(objeto)}' (el "
                f"'{node.hook.owner_type}' de una cota): el tipo no lo define",
                ln=expr.ln, col=expr.col)
        args = [valor]
        args.extend(self._argumentos(node.args, frame))
        return self.call_function(method[0], method[1], args,
                                  ln=expr.ln, col=expr.col)

    def _eval_callee(self, callee, frame: Frame) -> Any:
        """El callee de una llamada: soporta 'IO.printf' (miembro de un
        namespace) ademas de cualquier expresión que produzca una fn."""
        if callee.WhichOneof("node") == "member":
            if self._is_method_value(callee):
                return self._method_value(callee)
            base = self.eval_expr(callee.member.obj, frame)
            if isinstance(base, Namespace):
                return self._namespace_member(base, callee.member.member,
                                              ln=callee.ln, col=callee.col)
        return self.eval_expr(callee, frame)

    def _expr_index(self, expr, frame: Frame) -> Any:
        node = expr.index
        base = self.eval_expr(node.obj, frame)
        idx = self.eval_expr(node.index, frame)
        # 'v[i]' sobre un tipo NOMINAL con hook __index__: despacha al hook
        # (v.gr. un vector de librería). El indexado crudo de puntero/bloque
        # sigue por _element_cell.
        # 's[i]' sobre una CADENA: nativo, igual que 'len(s)'. Una cadena es
        # inmutable y sus elementos son code points, asi que el indice cuenta
        # CARACTERES y no bytes — es lo mismo que cuenta 'len', y contar dos
        # cosas distintas con la misma cadena habria sido la trampa.
        if isinstance(base, str):
            if not isinstance(idx, int) or isinstance(idx, bool):
                raise IndexOutOfRangeError(
                    f"el indice de una cadena es un entero, no "
                    f"{format_value(idx)}", ln=expr.ln, col=expr.col)
            if idx < 0 or idx >= len(base):
                raise IndexOutOfRangeError(
                    f"indice {idx} fuera de la cadena (longitud {len(base)})",
                    ln=expr.ln, col=expr.col)
            return base[idx]
        despacho = self._hook_de_indexado(base, self._index_kind,
                                          ln=expr.ln, col=expr.col)
        if despacho is not None:
            bound, receptor = despacho
            return self.call_function(bound[0], bound[1], [receptor, idx],
                                      ln=expr.ln, col=expr.col)
        return self._element_cell(base, idx, ln=expr.ln, col=expr.col).read(
            ln=expr.ln, col=expr.col)

    def _hook_de_indexado(self, base: Any, kind: int, *, ln: int, col: int):
        """``(hook, receptor)`` si ``base[i]`` despacha a ``__index__`` /
        ``__index_set__``; ``None`` si es indexado crudo.

        Vale para el valor Y para un PUNTERO a una celda que lo contiene: la
        Semántica ya tipaba ``v[i]`` con ``v: Vector<T> ptr`` a través del
        hook (igual que ``v.len()`` se desreferencia solo), y el intérprete lo
        indexaba como memoria cruda — ``RT013: solo [0] es válido``. Con el
        puntero, el receptor que recibe el hook es el PROPIO puntero, así que
        ``__index_set__`` escribe en el original y no en una copia. Un puntero
        a un BLOQUE (``mem.reserve``) sigue siendo indexado crudo.
        """
        objetivo = base
        if isinstance(base, Pointer):
            objetivo = base.deref(ln=ln, col=col)
        if not isinstance(objetivo, StructValue):
            return None
        bound = self.image.hooks.get(hook_key(objetivo.type_name, kind))
        if bound is None:
            return None
        return bound, base

    def _is_method_value(self, expr) -> bool:
        """¿``expr`` (un MemberAccess) es ``Tipo.metodo``? Lo marca la
        Semantica: el ``obj`` lleva el tipo META (nombra un tipo, no es un
        valor que evaluar) y el acceso, un tipo FUNCTION."""
        obj = expr.member.obj
        if not expr.type_id or not obj.type_id:
            return False
        types = self.unit.module.types
        return types[expr.type_id].kind == _TK_FUNCTION \
            and types[obj.type_id].kind == _TK_META

    def _method_value(self, expr) -> FunctionValue:
        """El valor de ``Tipo.metodo``: el cuerpo del metodo de ``@impl``.

        El dueño sale del RECEPTOR, el primer parametro del tipo funcion (ya
        canonico), y no del nombre escrito, que puede ir cualificado por un
        alias del modulo que solo existe en esta unidad."""
        fn_type = self.unit.module.types[expr.type_id]
        receiver = fn_type.args[0] if fn_type.args else None
        while receiver is not None and receiver.kind in (
                _TK_POINTER, _TK_NULLABLE) and receiver.HasField("inner"):
            receiver = receiver.inner
        owner = receiver.name if receiver is not None else ""
        method = self.image.dunders.get((owner, expr.member.member))
        if method is None:
            raise NotCallableError(
                f"'{owner}' no tiene el metodo '{expr.member.member}' en "
                "ejecucion", ln=expr.ln, col=expr.col)
        unit, decl = method
        return FunctionValue(unit.alias, decl,
                             display_name=f"{owner.rsplit('.', 1)[-1]}."
                                    f"{expr.member.member}")

    def _expr_member(self, expr, frame: Frame) -> Any:
        node = expr.member
        if self._is_method_value(expr):
            return self._method_value(expr)
        base = self.eval_expr(node.obj, frame)
        if isinstance(base, Namespace):
            return self._namespace_member(base, node.member,
                                          ln=expr.ln, col=expr.col)
        if isinstance(base, EnumNamespace):
            value = base.items.get(node.member)
            if value is None:
                raise UnsupportedNodeError(
                    f"'{base.name}' no define '{node.member}'",
                    ln=expr.ln, col=expr.col,
                )
            return value
        return self._field_cell(base, node.member,
                                ln=expr.ln, col=expr.col).read(
                                    ln=expr.ln, col=expr.col)

    def _expr_lambda(self, expr, frame: Frame) -> LambdaValue:
        """Una ``lambda`` vale su cuerpo y el marco ACTUAL: lo que captura
        (``LambdaExpr.captures``) se lee de ahi cuando se la llama. No se
        copia nada al crearla, y no hace falta: no escapa."""
        return LambdaValue(self.unit, expr.lambda_expr, frame, expr.ln, expr.col)

    def _expr_struct_literal(self, expr, frame: Frame) -> Any:
        node = expr.struct_literal
        valores = self._argumentos(node.values, frame)
        # un CAMPO se liga como una variable: 'Caja{ c: x }' guarda una copia
        # de 'x'. Antes guardaba el mismo objeto, y quien recibia la caja sin
        # copiarla (un 'return', un receptor) compartia su campo con 'x'.
        fields: dict = {name: Cell(self._ligado(expr, valor), name=name)
                        for name, expr, valor in zip(node.field_names,
                                                     node.values, valores)}
        return StructValue(node.type_name, fields)

    def _expr_sizeof(self, expr, frame: Frame) -> Any:
        node = expr.sizeof
        if node.hook.owner_type:
            bound = self.image.hooks.get(ref_key(node.hook))
            if bound is not None:
                return self.call_function(bound[0], bound[1], [None],
                                          ln=expr.ln, col=expr.col)
        raise UnsupportedNodeError(
            "sizeof sin '__sizeof__' declarado: el layout nativo es del backend",
            ln=expr.ln, col=expr.col,
        )

    def _expr_cast(self, expr, frame: Frame) -> Any:
        node = expr.cast_expr
        value = self.eval_expr(node.value, frame)
        kind = node.type.kind

        # conversiones NATIVAS entre primitivos (misma tabla que SEM016)
        if kind == _TK_INT:
            if isinstance(value, str):  # char -> int
                return ord(value)
            if isinstance(value, (bool, float, int)):
                return int(value)
        elif kind == _TK_FLOAT and isinstance(value, (int, float)):
            return float(value)
        elif kind == _TK_CHAR and isinstance(value, int):
            # un 'char' es un valor escalar de Unicode: 0..0x10FFFF sin los
            # sustitutos (0xD800..0xDFFF), que solo existen en UTF-16 y no se
            # pueden escribir. Antes: un fallo interno ('chr()'), o un
            # sustituto que reventaba al imprimirlo.
            if not 0 <= value <= 0x10FFFF or 0xD800 <= value <= 0xDFFF:
                raise ConversionError(
                    f"{value} no es un carácter: un 'char' va de 0 a 1114111 "
                    "(0x10FFFF), sin 55296..57343 (0xD800..0xDFFF)",
                    ln=expr.ln, col=expr.col)
            return chr(value)
        elif kind == _TK_BOOL and isinstance(value, bool):
            return value
        elif kind == _TK_BYTE and isinstance(value, int) and not isinstance(value, bool):
            return value & 0xFF   # trunca (modulo 256), como la VM
        elif kind == _TK_STR and isinstance(value, (str, bool, int, float)):
            # primitivo -> 'str': la MISMA representacion que interpola un
            # f-string ('format_value'), y no 'str()' de Python, porque si
            # divergieran 'cast<str>(true)' y f"{true}" darian dos textos
            # distintos para el mismo valor.
            return value if isinstance(value, str) else format_value(value)

        # tabla de conversiones (__cast__): par (origen estático, destino).
        # El origen es el tipo de la expresión, que viaja como ÍNDICE en el
        # pool de su unidad (Expr.type_id); el destino va inline en el nodo.
        # Hace falta el par completo porque un tipo puede declarar VARIAS
        # conversiones ('int -> int8' y 'float -> int8'), y el HookRef del
        # nodo —(dueño, clase, nombre)— no las distingue.
        # 'cast<TType>(1)' hacia un ENUM sin payload: el valor ya ES el
        # entero, asi que la conversion no transforma nada — solo le pone
        # nombre, y el nombre es cosa de la compilacion. La Semantica ya
        # comprobo que el literal sea uno de los declarados; aqui no queda
        # trabajo. Va ANTES de la tabla para que un enum no necesite declarar
        # un '__cast__' que no haria nada.
        if self._es_enum(node.type) and isinstance(value, int) \
                and not isinstance(value, bool):
            # ...salvo darle su nombre al valor: el item que lo lleva, para
            # que un genérico lo escriba como 'VERDE' y no como '1' (A08)
            return self._enum_item_of(node.type.name, value)

        destino = type_key(node.type)
        bound = self.image.casts.get((self._tipo_de(node.value), destino))
        if bound is not None:
            # un '__cast__' declarado como PROTOTIPO lo resuelve el host. No
            # sirve el registro por NOMBRE de 'call_function': todos se llaman
            # '__cast__' y lo que los distingue es el tipo DESTINO, que solo
            # se conoce aquí (mismo motivo por el que el par viaja en
            # 'image.casts' y no en el HookRef del nodo).
            if not bound[1].HasField("body"):
                nativa = intrinsics.lookup_cast(node.type.name)
                if nativa is not None:
                    try:
                        return nativa(value)
                    except SuriaXRuntimeError as exc:
                        raise exc.ubicar(expr.ln, expr.col)
            return self.call_function(bound[0], bound[1], [value],
                                      ln=expr.ln, col=expr.col)
        raise InvalidCastRuntimeError(
            f"sin conversión registrada para este par (valor: "
            f"{format_value(value)})", ln=expr.ln, col=expr.col,
        )

    def _es_enum(self, tipo) -> bool:
        """¿``tipo`` nombra un enum SIN payload de la unidad activa?

        La respuesta esta en la tabla de simbolos que el HIR ya transporta
        (``Module.symbols.types``), asi que no hace falta un dato nuevo en el
        esquema ni que el frontend marque el nodo: el interprete pregunta lo
        mismo que pregunto la Semantica.
        """
        if tipo.kind != _TK_NOMINAL or not tipo.name:
            return False
        sym = self.unit.module.symbols.types.get(tipo.name)
        if sym is None or sym.kind != _SK_ENUM:
            return False
        # con payload el enum es un tipo suma: sus valores no son enteros.
        return not any(m.param_types for m in sym.members.values())

    def _enum_item_of(self, name: str, value: int) -> int:
        """El :class:`EnumItem` de valor ``valor`` del enum ``nombre`` (o el
        mismo entero si ninguno vale eso: la Semántica ya comprobó el literal,
        así que no debería pasar)."""
        enum = self._enum_de(name, self.unit)
        if enum is not None:
            owner, decl = enum
            for item in owner.enum_values.get(decl.name, {}).values():
                if isinstance(item, EnumItem) and item == value:
                    return item
        return value

    def _es_byte(self, expr) -> bool:
        """¿El tipo estatico de ``expr`` es ``byte``?"""
        if not expr.type_id:
            return False
        return self.unit.module.types[expr.type_id].kind == _TK_BYTE

    def _tipo_de(self, expr):
        """Clave del tipo estático de ``expr``, resuelta contra el pool de la
        unidad activa. ``0`` = sin tipo anotado (el esquema lo permite), y
        entonces no hay clave que buscar."""
        if not expr.type_id:
            return None
        return type_key(self.unit.module.types[expr.type_id])

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _namespace_member(self, ns: Namespace, member: str, *,
                          ln: int, col: int) -> Any:
        unit = self.image.units.get(ns.alias)
        if unit is None:
            raise NotCallableError(
                f"la unidad '{ns.alias}' no está ligada en la imagen",
                ln=ln, col=col,
            )
        decl = unit.functions.get(member)
        if decl is not None:
            return FunctionValue(unit.alias, decl)
        cell = unit.globals_frame.try_lookup(member) if unit.globals_frame else None
        if cell is not None:
            return cell.read(ln=ln, col=col)
        # ...y si la unidad es el PADRE de un paquete, el miembro puede ser un
        # submódulo: son unidades hermanas calificadas ('IO' + 'IO.stdp'), no
        # declaraciones del padre. Una sola búsqueda en dict, sin listar nada.
        sub = self.image.units.get(f"{ns.alias}.{member}")
        if sub is not None:
            return Namespace(sub.alias)
        raise NotCallableError(
            f"'{ns.alias}' no expone '{member}' en runtime", ln=ln, col=col,
        )

    def _element_cell(self, base: Any, index: Any, *, ln: int, col: int) -> Cell:
        """Celda del elemento ``base[index]`` (secc. 8.x — memoria contigua).

        Opera sobre un :class:`Block` de ``__reserve__`` (el caso de los
        vectores) o, por comodidad, sobre un puntero a UNA celda (índice 0).
        Como ``&buf[i]``, lectura y escritura por índice comparten destino con
        el resto del sistema de memoria (la celda es la única dueña del estado).
        """
        if isinstance(base, Block):
            return base.element(index, ln=ln, col=col)
        if isinstance(base, Pointer):
            block = base.deref(ln=ln, col=col)
            if isinstance(block, Block):  # puntero al bloque reservado
                return block.element(index, ln=ln, col=col)
            if index == 0:  # puntero a una sola celda: solo [0]
                return base.cell
            raise IndexOutOfRangeError(
                f"índice {index!r} sobre un puntero a una sola celda "
                "(solo [0] es válido)", ln=ln, col=col)
        if base is None:
            raise NullDereferenceError(
                f"indexación '[{index!r}]' sobre null", ln=ln, col=col)
        raise NotIndexableError(
            f"'{format_value(base)}' no es indexable (usa un bloque de "
            "__reserve__)", ln=ln, col=col)

    def _field_cell(self, base: Any, field: str, *, ln: int, col: int) -> Cell:
        """Celda del campo ``base.field`` con DEREF IMPLÍCITO de punteros
        (``s.text`` con ``s: String ptr`` — secc. 8.2)."""
        base = self._pointee(base, ln=ln, col=col)
        if base is None:
            raise NullDereferenceError(
                f"acceso a '.{field}' sobre null", ln=ln, col=col,
            )
        if isinstance(base, StructValue):
            cell = base.fields.get(field)
            if cell is None:
                raise UnsupportedNodeError(
                    f"'{base.type_name}' no tiene campo '{field}'",
                    ln=ln, col=col,
                )
            return cell
        raise UnsupportedNodeError(
            f"acceso a miembro '.{field}' sobre {format_value(base)}",
            ln=ln, col=col,
        )

    def _tick(self, ln: int, col: int) -> None:
        if self.max_steps:
            self.steps += 1
            if self.steps > self.max_steps:
                raise StepLimitError(
                    f"límite de pasos alcanzado ({self.max_steps}); ajusta "
                    "'interpreter.max_steps' en .suriaX_config.yaml",
                    ln=ln, col=col,
                )


__all__ = ["Evaluator", "ExpectFallido", "Thrown"]
